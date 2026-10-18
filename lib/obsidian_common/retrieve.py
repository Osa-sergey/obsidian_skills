"""obsidian-retrieve's orchestration core: combine Omnisearch (keyword),
RAPTOR semantic search, and graph/MOC proximity into one deduplicated,
budget-aware CandidateSet.

Spec 14: "построить search plan; при возможности выполнить Dataview/Bases
pre-filter; запустить нужные retrievers; объединить и дедуплицировать
результаты; учесть MOC/graph proximity; оценить стоимость чтения;
сформировать CandidateSet." Honest scope note: Dataview/Bases pre-filter
is not implemented here yet (skills 11/12 aren't built) - this module
runs the two retrievers that exist (Omnisearch, semantic) plus graph
expansion, and says so in CandidateSetResult rather than silently
pretending pre-filtering happened.

File-level candidates, not node-level: a Candidate is one vault note,
carrying the best evidence found for it from each retriever plus a
recommended *node* to actually read next (the best-scoring semantic node
inside it, if any) - obsidian-fragment-reader does the real reading.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from . import linkgraph
from . import semantic
from .embeddings import EmbeddingUnavailable
from .omnisearch import OmnisearchClient, OmnisearchUnavailable, clean_excerpt, filter_by_vault
from .profile import VaultProfile
from .vectorstore import VectorStoreUnavailable

CHARS_PER_TOKEN = 4  # same rough heuristic as raptor.py/summarizer.py


@dataclass
class Candidate:
    source_path: str
    reasons: List[str] = field(default_factory=list)
    omnisearch_score: Optional[float] = None
    omnisearch_excerpt: Optional[str] = None
    semantic_score: Optional[float] = None
    semantic_match: Optional[semantic.RaptorMatch] = None  # best node-level hit in this file
    graph_distance: Optional[int] = None
    graph_direction: Optional[str] = None  # outlink | backlink
    combined_score: float = 0.0
    estimated_read_tokens: int = 0


@dataclass
class CandidateSetResult:
    mode: str
    candidates: List[Candidate]
    retrievers_used: List[str]
    retrievers_skipped: Dict[str, str]  # name -> reason (e.g. "embeddings_unavailable")
    vault_mismatch_warning: Optional[str]
    budget_max_tokens: int
    budget_used_tokens: int
    budget_truncated: bool
    recommendations: List[str]


def _normalize(scores: Dict[str, float]) -> Dict[str, float]:
    """Min-max normalize within this run's own results - Omnisearch and
    cosine-similarity scores live on different, arbitrary scales, so a
    hardcoded cross-mechanism threshold would be meaningless. Falls back
    to 1.0 for every entry when all scores are equal (avoids a divide by
    zero, and a flat set of scores really is "equally relevant so far")."""
    if not scores:
        return {}
    lo, hi = min(scores.values()), max(scores.values())
    if hi == lo:
        return {k: 1.0 for k in scores}
    return {k: (v - lo) / (hi - lo) for k, v in scores.items()}


def _run_omnisearch(profile: VaultProfile, queries: List[str]) -> tuple:
    """Returns (candidates_by_path, warning, skip_reason)."""
    if not profile.omnisearch.enabled:
        return {}, None, "disabled in profile"
    client = OmnisearchClient(profile.omnisearch.host, profile.omnisearch.port, profile.omnisearch.timeout)
    expected_vault = profile.vault_path.name
    merged: Dict[str, Candidate] = {}
    warning = None
    try:
        for q in queries:
            hits = client.search(q)
            hits, w = filter_by_vault(hits, expected_vault)
            warning = warning or w
            for h in hits:
                c = merged.setdefault(h.path, Candidate(source_path=h.path))
                if c.omnisearch_score is None or h.score > c.omnisearch_score:
                    c.omnisearch_score = h.score
                    c.omnisearch_excerpt = clean_excerpt(h.excerpt)
                if "omnisearch" not in c.reasons:
                    c.reasons.append("omnisearch")
    except OmnisearchUnavailable as exc:
        return merged, warning, f"omnisearch_unavailable: {exc}"
    return merged, warning, None


def _run_semantic(profile: VaultProfile, queries: List[str], top_k: int) -> tuple:
    """Returns (candidates_by_path, skip_reason)."""
    if not profile.embeddings.enabled:
        return {}, "embeddings disabled in profile"
    merged: Dict[str, Candidate] = {}
    try:
        for q in queries:
            matches = semantic.search(profile, q, top_k=top_k)
            for m in matches:
                c = merged.setdefault(m.source_path, Candidate(source_path=m.source_path))
                if c.semantic_score is None or m.score > c.semantic_score:
                    c.semantic_score = m.score
                    c.semantic_match = m
                if "semantic" not in c.reasons:
                    c.reasons.append("semantic")
    except (EmbeddingUnavailable, VectorStoreUnavailable) as exc:
        return merged, str(exc)
    return merged, None


def _estimate_read_tokens(c: Candidate) -> int:
    if c.semantic_match:
        span = max(1, c.semantic_match.line_end - c.semantic_match.line_start)
        return span * 12  # ~12 chars/line rough average, /4 chars-per-token below
    return 2000  # unknown extent (omnisearch/graph-only hit) - conservative whole-note guess


def build_candidate_set(
    profile: VaultProfile, queries: List[str], mode: str = "narrow", top_k: int = 10,
) -> CandidateSetResult:
    if mode not in ("narrow", "deep"):
        raise ValueError("mode must be 'narrow' or 'deep'")
    limits = profile.limits_for(mode)

    retrievers_used: List[str] = []
    retrievers_skipped: Dict[str, str] = {}

    om_candidates, vault_warning, om_skip = _run_omnisearch(profile, queries)
    if om_skip:
        retrievers_skipped["omnisearch"] = om_skip
    elif om_candidates or profile.omnisearch.enabled:
        retrievers_used.append("omnisearch")

    sem_candidates, sem_skip = _run_semantic(profile, queries, top_k)
    if sem_skip:
        retrievers_skipped["semantic"] = sem_skip
    elif sem_candidates or profile.embeddings.enabled:
        retrievers_used.append("semantic")

    merged: Dict[str, Candidate] = {}
    for path, c in om_candidates.items():
        merged[path] = c
    for path, c in sem_candidates.items():
        if path in merged:
            merged[path].semantic_score = c.semantic_score
            merged[path].semantic_match = c.semantic_match
            merged[path].reasons.append("semantic")
        else:
            merged[path] = c

    # Graph/MOC proximity - deep mode only (spec: "deep... больше MOC/graph
    # expansion"); narrow mode stays high-precision and skips this to avoid
    # pulling in loosely-related neighbors.
    if mode == "deep" and merged:
        seed_paths = [c.source_path for c in
                      sorted(merged.values(), key=lambda c: max(c.omnisearch_score or 0, c.semantic_score or 0),
                             reverse=True)[:5]]
        bfs = linkgraph.bfs_context(
            profile.vault_path, profile.scope, seed_paths, direction="both",
            max_depth=limits.graph_depth, max_notes=limits.max_notes, max_neighbors=limits.max_neighbors,
        )
        retrievers_used.append("graph")
        for node in bfs.nodes:
            if node.depth == 0:
                continue  # seed itself, already a candidate with a real score
            c = merged.setdefault(node.path, Candidate(source_path=node.path))
            if c.graph_distance is None or node.depth < c.graph_distance:
                c.graph_distance = node.depth
                c.graph_direction = node.direction
            if "graph" not in c.reasons:
                c.reasons.append(f"graph:{node.direction}")

    om_norm = _normalize({p: c.omnisearch_score for p, c in merged.items() if c.omnisearch_score is not None})
    sem_norm = _normalize({p: c.semantic_score for p, c in merged.items() if c.semantic_score is not None})
    for path, c in merged.items():
        score = 0.5 * om_norm.get(path, 0.0) + 0.5 * sem_norm.get(path, 0.0)
        if c.graph_distance is not None:
            score += max(0.0, 0.1 * (limits.graph_depth - c.graph_distance + 1) / (limits.graph_depth + 1))
        c.combined_score = round(score, 4)
        c.estimated_read_tokens = _estimate_read_tokens(c) // CHARS_PER_TOKEN

    ranked = sorted(merged.values(), key=lambda c: c.combined_score, reverse=True)

    budget_max = limits.max_tokens
    kept: List[Candidate] = []
    used = 0
    truncated = False
    for c in ranked[: limits.max_notes]:
        if used + c.estimated_read_tokens > budget_max and kept:
            truncated = True
            break
        kept.append(c)
        used += c.estimated_read_tokens
    if len(ranked) > limits.max_notes:
        truncated = True

    recommendations = []
    if kept:
        top = kept[0]
        if top.semantic_match:
            recommendations.append(
                f"Read first: {top.source_path} @ {' > '.join(top.semantic_match.heading_path) or '(article root)'} "
                f"(lines {top.semantic_match.line_start}-{top.semantic_match.line_end}) via obsidian-fragment-reader."
            )
        else:
            recommendations.append(f"Read first: {top.source_path} (no addressed node - read via obsidian-search's excerpt or the whole file).")
    if truncated:
        recommendations.append(
            f"{len(ranked) - len(kept)} more candidate(s) were cut by the {mode} budget "
            f"(max_notes={limits.max_notes}, max_tokens={budget_max}) - rerun with mode=deep for a wider pass."
        )
    if not retrievers_used:
        recommendations.append("No retriever actually ran - check retrievers_skipped before trusting an empty result.")

    return CandidateSetResult(
        mode=mode, candidates=kept, retrievers_used=retrievers_used, retrievers_skipped=retrievers_skipped,
        vault_mismatch_warning=vault_warning, budget_max_tokens=budget_max, budget_used_tokens=used,
        budget_truncated=truncated, recommendations=recommendations,
    )
