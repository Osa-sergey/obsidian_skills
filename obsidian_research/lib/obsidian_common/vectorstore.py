"""Vector store: Qdrant, reached over HTTP by default (ADR-0009, revised).

The collection lives per-vault: `<collection_prefix>_<vault_id>` (default
prefix "raptor"), so several vaults can share one Qdrant instance without
their points mixing. One RaptorNode (lib/obsidian_common/raptor.py) becomes
one Qdrant point, keyed by its own `node_id` (already a stable UUID) - a
resync just re-upserts the same IDs, no separate "insert vs update" logic
needed downstream.

Two named vectors per point (by user directive, not the original ADR-0009
single-vector design): "summary" and "raw". Every node gets a "summary"
vector - for a chunk/callout leaf that's just its own text (there's nothing
to summarize); for article/section/subsection it's the LLM-generated
summary of the whole subtree (lib/obsidian_common/summarizer.py). "raw" is
present only when the node's own full, unsummarized text is small enough
to be a useful embedding on its own (see raptor.raw_text_for_node's size
guard) - Qdrant supports points that omit a named vector entirely (verified
against a real container: a point missing "raw" simply never matches a
`using="raw"` query, no error, no placeholder needed).

ADR-0006/REQ-RET-0001-0002: the vector store is never the source of truth
and a changed file gets its vectors fully replaced, not diffed - hence
`delete_by_source_path` exists and is meant to run right before a fresh
`upsert_nodes` for that file, not instead of it.

Two `VectorStoreConfig.mode` values (profile.py):
  "http"  - default: `QdrantClient(host=..., port=...)` against a
            long-running `qdrant/qdrant` Docker container.
  "local" - embedded, in-process `QdrantClient(path=...)`, no server; kept
            as a fallback for a machine without Docker (ADR-0009's
            original starting point).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from qdrant_client import QdrantClient
from qdrant_client.http.exceptions import UnexpectedResponse
from qdrant_client.models import (
    Distance,
    FieldCondition,
    Filter,
    MatchAny,
    MatchValue,
    PointStruct,
    VectorParams,
)

from .profile import VaultProfile
from .raptor import RaptorNode

VECTOR_NAMES = ("summary", "raw")


class VectorStoreUnavailable(RuntimeError):
    """The configured Qdrant instance is unreachable, or the collection's
    pinned embedding dimension doesn't match what's being written -
    callers should degrade to an explicit `embeddings_unavailable`/
    `index_dirty` state (CLAUDE.md invariant 6), never claim a stale
    index is current."""


@dataclass
class ScoredNode:
    node_id: str
    score: float
    payload: dict


def _collection_name(profile: VaultProfile) -> str:
    return f"{profile.vectorstore.collection_prefix}_{profile.vault_id}"


def get_client(profile: VaultProfile) -> QdrantClient:
    vs = profile.vectorstore
    try:
        if vs.mode == "local":
            return QdrantClient(path=str(profile.vector_store_path))
        return QdrantClient(host=vs.host, port=vs.port, timeout=10.0)
    except Exception as exc:  # noqa: BLE001 - qdrant-client raises a mix of types here
        raise VectorStoreUnavailable(
            f"could not open Qdrant client (mode={vs.mode}): {exc}"
        ) from exc


def ping(profile: VaultProfile) -> bool:
    try:
        get_client(profile).get_collections()
        return True
    except Exception:
        return False


def ensure_collection(client: QdrantClient, profile: VaultProfile, dimension: int) -> None:
    """Get-or-create the vault's collection, pinned to `dimension` for both
    named vectors ("summary" and "raw" always share the same embedding
    model/width - there's only one embeddings server per profile). A
    dimension mismatch against an existing collection means a model/
    embedding-width change happened without a full reindex (ADR-0009's
    "Условия пересмотра") - fail loudly rather than silently corrupt or
    silently drop the old vectors."""
    name = _collection_name(profile)
    try:
        existing = client.get_collection(name)
        existing_vectors = existing.config.params.vectors
        existing_dim = existing_vectors[VECTOR_NAMES[0]].size
        if existing_dim != dimension:
            raise VectorStoreUnavailable(
                f"collection {name!r} is pinned to dimension {existing_dim}, "
                f"but this run computed {dimension} - the embedding model or "
                "its width changed. Rebuild the whole index (delete the "
                "collection and resync every file), see ADR-0009."
            )
        return
    except (UnexpectedResponse, ValueError):
        pass  # collection does not exist yet
    client.create_collection(
        collection_name=name,
        vectors_config={
            name_: VectorParams(size=dimension, distance=Distance.COSINE)
            for name_ in VECTOR_NAMES
        },
    )


def upsert_nodes(
    client: QdrantClient, profile: VaultProfile,
    nodes: List[RaptorNode], vectors: List[Dict[str, List[float]]],
) -> None:
    """`vectors[i]` is a dict with a required "summary" key and an optional
    "raw" key - a node whose raw text was too large to embed on its own
    (see raptor.raw_text_for_node) simply omits "raw", and that point never
    matches a `using="raw"` query afterwards."""
    if len(nodes) != len(vectors):
        raise ValueError(f"{len(nodes)} nodes but {len(vectors)} vectors")
    if not nodes:
        return
    for vec in vectors:
        if "summary" not in vec:
            raise ValueError(f"every node needs a 'summary' vector, got keys {list(vec)}")
    points = [
        PointStruct(id=n.node_id, vector=vec, payload=n.to_payload())
        for n, vec in zip(nodes, vectors)
    ]
    client.upsert(collection_name=_collection_name(profile), points=points)


def delete_by_source_path(client: QdrantClient, profile: VaultProfile, source_path: str) -> None:
    """Full-replacement delete (ADR-0006/REQ-RET-0001-0002): call this
    before re-upserting a changed file's nodes, and on its own when a file
    is removed from the vault."""
    name = _collection_name(profile)
    try:
        client.get_collection(name)
    except (UnexpectedResponse, ValueError):
        return  # nothing indexed yet for this vault
    client.delete(
        collection_name=name,
        points_selector=Filter(
            must=[FieldCondition(key="source_path", match=MatchValue(value=source_path))]
        ),
    )


def count_by_source_path(client: QdrantClient, profile: VaultProfile, source_path: str) -> int:
    """How many points currently exist for a path - used by index-sync's
    `status` to report what's actually indexed without doing a full query,
    and by its own post-write self-check (spec 18 step 6: "сверить...
    число записанных узлов")."""
    name = _collection_name(profile)
    try:
        client.get_collection(name)
    except (UnexpectedResponse, ValueError):
        return 0
    result = client.count(
        collection_name=name,
        count_filter=Filter(must=[FieldCondition(key="source_path", match=MatchValue(value=source_path))]),
    )
    return result.count


def query(
    client: QdrantClient, profile: VaultProfile, query_vector: List[float], limit: int = 10,
    node_levels: Optional[List[str]] = None, using: str = "summary",
) -> List[ScoredNode]:
    """`using` picks which named vector space to search - "summary" (the
    default) covers every node in the tree, since every node has one;
    "raw" only matches nodes small enough to have gotten a raw-text
    vector too (see module docstring)."""
    if using not in VECTOR_NAMES:
        raise ValueError(f"using must be one of {VECTOR_NAMES}, got {using!r}")
    name = _collection_name(profile)
    query_filter = None
    if node_levels:
        query_filter = Filter(
            must=[FieldCondition(key="node_level", match=MatchAny(any=node_levels))]
        )
    try:
        result = client.query_points(
            collection_name=name, query=query_vector, using=using,
            limit=limit, query_filter=query_filter,
        )
    except (UnexpectedResponse, ValueError) as exc:
        raise VectorStoreUnavailable(f"query against {name!r} failed: {exc}") from exc
    return [ScoredNode(node_id=str(p.id), score=p.score, payload=p.payload or {}) for p in result.points]


def get_by_ids(client: QdrantClient, profile: VaultProfile, node_ids: List[str]) -> List[ScoredNode]:
    """Direct lookup by node_id, no vector search - progressive disclosure
    (spec 13: "при высокой релевантности раскрывать дочерние узлы") walks
    `child_ids`/`parent_id` from an already-found node's payload rather
    than re-querying by vector. `score` is always 1.0 here since there was
    no similarity computation - callers should not sort by it."""
    if not node_ids:
        return []
    name = _collection_name(profile)
    try:
        points = client.retrieve(collection_name=name, ids=node_ids, with_payload=True)
    except (UnexpectedResponse, ValueError) as exc:
        raise VectorStoreUnavailable(f"retrieve against {name!r} failed: {exc}") from exc
    return [ScoredNode(node_id=str(p.id), score=1.0, payload=p.payload or {}) for p in points]
