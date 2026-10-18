"""Per-file RAPTOR indexing pipeline: delete-old -> chunk -> summarize ->
embed -> write-new. Backs obsidian-index-sync (skill 18); kept in lib so
the CLI script stays thin (arg parsing + change-event bookkeeping only)
and so a future write coordinator can call this directly.

ADR-0006's ordering is load-bearing, not incidental: old vectors for a
path are deleted *before* the file is rebuilt, not after. A crash between
those two steps leaves the file with zero vectors rather than stale ones
- worse for recall until retried, but never silently wrong, which is the
property CLAUDE.md invariant 6 actually asks for ("не утверждать
актуальность поиска" beats "keep something, even if wrong, around").
Every failure path below returns "index_dirty" with an `error` string
instead of raising, so a caller indexing many files can keep going and
report per-file status rather than aborting the whole batch on one bad
file (spec 18's "для частично применённого пакета передаются только
реально совершённые изменения").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import raptor
from . import vectorstore as vs
from .embeddings import EmbeddingClient, EmbeddingUnavailable
from .profile import VaultProfile
from .summarizer import LLMSummarizer


@dataclass
class IndexFileResult:
    source_path: str
    status: str  # indexed | deleted | not_indexable | index_dirty
    nodes_written: int = 0
    nodes_deleted_first: bool = False
    summary_fallback_nodes: List[str] = field(default_factory=list)
    dimension: Optional[int] = None
    error: Optional[str] = None


def _embedding_client(profile: VaultProfile) -> EmbeddingClient:
    e = profile.embeddings
    return EmbeddingClient(host=e.host, port=e.port, model=e.model, api_key=e.api_key, timeout=e.timeout)


def _summarizer(profile: VaultProfile) -> LLMSummarizer:
    s = profile.summarizer
    return LLMSummarizer(
        host=s.host, port=s.port, model=s.model, api_key=s.api_key,
        timeout=s.timeout, temperature=s.temperature, max_tokens=s.max_tokens,
    )


def index_file(profile: VaultProfile, source_path: str, raw_text: str) -> IndexFileResult:
    """Full replacement of one file's vectors (ADR-0006/REQ-RET-0001-0002).
    `raw_text` is the already-read current file content - this function
    does no filesystem I/O itself, matching every other lib module's
    "caller reads, we just process" shape."""
    if not profile.vectorstore.enabled:
        return IndexFileResult(source_path, "index_dirty", error="vectorstore disabled in profile")

    try:
        qdrant = vs.get_client(profile)
        vs.delete_by_source_path(qdrant, profile, source_path)
    except vs.VectorStoreUnavailable as exc:
        return IndexFileResult(source_path, "index_dirty", error=f"delete of old vectors failed: {exc}")

    nodes = raptor.build_raptor_tree(raw_text, profile.vault_id, source_path)
    nodes_by_id = {n.node_id: n for n in nodes}

    fallback_nodes: List[str] = []
    if profile.summarizer.enabled:
        summarizer = _summarizer(profile)
        errors = raptor.fill_summaries(
            nodes, lambda texts: summarizer.summarize_token_aware(texts, profile.summarizer.max_tokens)
        )
        fallback_nodes = list(errors.keys())

    if not profile.embeddings.enabled:
        return IndexFileResult(
            source_path, "index_dirty", nodes_deleted_first=True,
            error="embeddings disabled in profile - old vectors were deleted, file currently has none indexed",
        )

    embedder = _embedding_client(profile)
    raw_texts_by_id: Dict[str, str] = {}
    for n in nodes:
        if n.node_level in ("article", "section", "subsection"):
            full = raptor.raw_text_for_node(n.node_id, nodes_by_id)
            if raptor.should_embed_raw(full):
                raw_texts_by_id[n.node_id] = full

    try:
        summary_result = embedder.embed([n.text for n in nodes])
        raw_ids = list(raw_texts_by_id.keys())
        raw_vectors_by_id: Dict[str, List[float]] = {}
        if raw_ids:
            raw_result = embedder.embed([raw_texts_by_id[nid] for nid in raw_ids])
            raw_vectors_by_id = dict(zip(raw_ids, raw_result.vectors))
    except EmbeddingUnavailable as exc:
        return IndexFileResult(
            source_path, "index_dirty", nodes_deleted_first=True,
            error=f"old vectors deleted but embedding failed, file currently has none indexed: {exc}",
        )

    vectors: List[Dict[str, List[float]]] = []
    for n, summary_vec in zip(nodes, summary_result.vectors):
        v: Dict[str, List[float]] = {"summary": summary_vec}
        if n.node_id in raw_vectors_by_id:
            v["raw"] = raw_vectors_by_id[n.node_id]
        vectors.append(v)

    try:
        vs.ensure_collection(qdrant, profile, summary_result.dimension)
        vs.upsert_nodes(qdrant, profile, nodes, vectors)
    except vs.VectorStoreUnavailable as exc:
        return IndexFileResult(
            source_path, "index_dirty", nodes_deleted_first=True,
            error=f"old vectors deleted but write failed, file currently has none indexed: {exc}",
        )

    return IndexFileResult(
        source_path, "indexed", nodes_written=len(nodes), nodes_deleted_first=True,
        summary_fallback_nodes=fallback_nodes, dimension=summary_result.dimension,
    )


def delete_file(profile: VaultProfile, source_path: str) -> IndexFileResult:
    """A file was removed from the vault - delete its vectors, never
    rebuild (spec 18 step 3: for `deleted`, stop right after confirming
    the delete; never read the now-gone file or build new vectors)."""
    if not profile.vectorstore.enabled:
        return IndexFileResult(source_path, "index_dirty", error="vectorstore disabled in profile")
    try:
        qdrant = vs.get_client(profile)
        vs.delete_by_source_path(qdrant, profile, source_path)
    except vs.VectorStoreUnavailable as exc:
        return IndexFileResult(source_path, "index_dirty", error=f"delete failed: {exc}")
    return IndexFileResult(source_path, "deleted", nodes_deleted_first=True)
