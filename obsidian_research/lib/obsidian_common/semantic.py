"""RAPTOR semantic search over the Qdrant index obsidian-index-sync builds.

Spec 13: search summary-level vectors first (covers every node in the
tree, since every node has a "summary" vector - see vectorstore.py); a
caller can narrow to specific node_levels, or explicitly search the "raw"
vector space (only section/subsection/article nodes small enough to have
one - see raptor.should_embed_raw). Progressive disclosure ("при высокой
релевантности раскрывать дочерние узлы") is `expand()`: given an
already-found node, fetch its children/parent directly by ID, no new
vector search.

Never returns node text - only enough to address a fragment-reader read
(source_path + line range + heading_path). foundation.md's "исходный
Markdown - источник истины": a generated summary is a *pointer* to real
text, never a substitute for reading it (see this module's `preview`
field, always the short extractive/generated stand-in, never the
full text).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .embeddings import EmbeddingClient
from .profile import VaultProfile
from . import vectorstore as vs


@dataclass
class RaptorMatch:
    node_id: str
    score: float
    source_path: str
    node_level: str  # article | section | subsection | chunk | callout
    heading_path: List[str]
    line_start: int
    line_end: int
    preview: str
    parent_id: Optional[str]
    child_ids: List[str] = field(default_factory=list)
    summary_source: str = ""
    vector_used: str = "summary"  # which named vector this match came from


def _to_match(scored: vs.ScoredNode, vector_used: str) -> RaptorMatch:
    p = scored.payload
    return RaptorMatch(
        node_id=scored.node_id, score=scored.score,
        source_path=p.get("source_path", ""), node_level=p.get("node_level", ""),
        heading_path=p.get("heading_path", []) or [], line_start=p.get("line_start", 0),
        line_end=p.get("line_end", 0), preview=p.get("preview", ""),
        parent_id=p.get("parent_id"), child_ids=p.get("child_ids", []) or [],
        summary_source=p.get("summary_source", ""), vector_used=vector_used,
    )


def search(
    profile: VaultProfile, query_text: str, top_k: int = 10,
    node_levels: Optional[List[str]] = None, using: str = "summary",
) -> List[RaptorMatch]:
    """One query embedding, one Qdrant search. Raises EmbeddingUnavailable
    or VectorStoreUnavailable on failure - callers must surface that as a
    degraded/incomplete result (spec 13's index_dirty rule), never
    silently return an empty match list that looks like "genuinely no
    hits"."""
    embedder = EmbeddingClient(
        host=profile.embeddings.host, port=profile.embeddings.port,
        model=profile.embeddings.model, api_key=profile.embeddings.api_key,
        timeout=profile.embeddings.timeout,
    )
    query_vector = embedder.embed_one(query_text)
    client = vs.get_client(profile)
    hits = vs.query(client, profile, query_vector, limit=top_k, node_levels=node_levels, using=using)
    return [_to_match(h, using) for h in hits]


def expand(profile: VaultProfile, node_ids: List[str]) -> List[RaptorMatch]:
    """Fetch specific nodes by ID directly - no similarity involved, every
    returned match has score=1.0 (do not sort by it). Used to walk
    `child_ids` from a high-scoring match (progressive disclosure into a
    section's chunks) or `parent_id` (walk up to see the surrounding
    heading)."""
    client = vs.get_client(profile)
    hits = vs.get_by_ids(client, profile, node_ids)
    return [_to_match(h, "none") for h in hits]
