"""obsidian-evidence's mechanical core: turn a set of addressed fragment
requests (usually derived from a CandidateSet - obsidian-retrieve's
output) into deduplicated, actually-fetched fragments, and validate a
Claude-authored EvidenceItem[] against them before it's presented as
proof of anything.

Spec 16: "запросить через fragment-reader исходные passages; объединить
дубли... EvidenceItem: claim/question facet, file, heading path,
fragment, paraphrase/short quote, directness, retrieval methods,
confidence, read cost." This module does the mechanical half (fetch +
dedup + read-cost + quote verification) - which claim a fragment actually
supports, how direct the support is, and how confident that judgment is
stay Claude's own call, the same division of labor as gap_search's
read-target/check-coverage (mechanical) vs "is this gap significant"
(Claude).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import markdown as md
from .pathutil import is_excluded
from .profile import VaultProfile

CHARS_PER_TOKEN = 4  # same rough heuristic as raptor.py/retrieve.py


@dataclass
class FragmentRequest:
    tag: str  # caller-supplied label (claim id, candidate source_path, ...) to trace back to
    path: str
    heading: Optional[str] = None
    block_id: Optional[str] = None
    line_range: Optional[tuple] = None  # (start, end) - end exclusive, matches read_fragment
    include_children: bool = False
    child_depth: int = 1


@dataclass
class FetchedFragment:
    fragment_id: str
    status: str  # resolved | not_found | needs_context | out_of_scope
    path: str
    heading_path: Optional[List[str]]
    line_start: Optional[int]
    line_end: Optional[int]
    text: Optional[str]
    content_hash: Optional[str]
    requested_for: List[str] = field(default_factory=list)
    candidates: Optional[list] = None  # needs_context: what read_fragment offered instead


def _fragment_id(path: str, line_start: Optional[int], line_end: Optional[int]) -> str:
    seed = f"{path}|{line_start}|{line_end}"
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[:12]


def fetch_fragments(profile: VaultProfile, requests: List[FragmentRequest]) -> List[FetchedFragment]:
    """Resolves every request via read_fragment, then collapses duplicates:
    two requests that resolve to the exact same (path, line_start,
    line_end) - or where one's range fully contains another's on the same
    path - are fetched/returned once, with `requested_for` listing every
    tag that asked for it. Partial (non-containing) overlaps are NOT
    merged into one fragment - a known simplification, see module
    docstring; each still gets its own entry."""
    resolved: List[FetchedFragment] = []
    for req in requests:
        if is_excluded(req.path, profile.scope):
            resolved.append(FetchedFragment(
                fragment_id=_fragment_id(req.path, None, None), status="out_of_scope",
                path=req.path, heading_path=None, line_start=None, line_end=None,
                text=None, content_hash=None, requested_for=[req.tag],
            ))
            continue
        r = md.read_fragment(
            profile.vault_path, req.path, heading_query=req.heading, block_id=req.block_id,
            line_range=req.line_range, include_children=req.include_children, child_depth=req.child_depth,
        )
        fid = _fragment_id(r.path, r.line_start, r.line_end) if r.status == "resolved" else _fragment_id(r.path, None, None) + f":{req.tag}"
        resolved.append(FetchedFragment(
            fragment_id=fid, status=r.status, path=r.path, heading_path=r.heading_path,
            line_start=r.line_start, line_end=r.line_end, text=r.text, content_hash=r.content_hash,
            requested_for=[req.tag], candidates=r.candidates,
        ))

    # Collapse: exact-range duplicates first (same fragment_id already
    # merges via dict), then containment (a smaller resolved range fully
    # inside an already-kept larger one on the same path).
    by_id: Dict[str, FetchedFragment] = {}
    order: List[str] = []
    for f in resolved:
        if f.fragment_id in by_id:
            by_id[f.fragment_id].requested_for.extend(f.requested_for)
        else:
            by_id[f.fragment_id] = f
            order.append(f.fragment_id)

    kept: List[FetchedFragment] = []
    for fid in order:
        f = by_id[fid]
        if f.status != "resolved":
            kept.append(f)
            continue
        container = next((
            k for k in kept
            if k.status == "resolved" and k.path == f.path
            and k.line_start <= f.line_start and k.line_end >= f.line_end
            and (k.line_start, k.line_end) != (f.line_start, f.line_end)
        ), None)
        if container:
            container.requested_for.extend(f.requested_for)
            continue
        # this fragment might itself contain an already-kept smaller one -
        # fold that one's tags in and drop it
        absorbed = [k for k in kept if k.status == "resolved" and k.path == f.path
                    and f.line_start <= k.line_start and f.line_end >= k.line_end
                    and (k.line_start, k.line_end) != (f.line_start, f.line_end)]
        for a in absorbed:
            f.requested_for.extend(a.requested_for)
            kept.remove(a)
        kept.append(f)

    for f in kept:
        f.requested_for = sorted(set(f.requested_for))
    return kept


@dataclass
class EvidenceValidationError:
    index: int
    field: str
    message: str


def validate_evidence_items(fetched: List[FetchedFragment], items: List[dict]) -> List[EvidenceValidationError]:
    """Mechanical checks only - never judges whether a claim is actually
    supported, only whether what's asserted is internally consistent and
    traceable to real fetched text:
    - `fragment_id` refers to something actually fetched and `resolved`.
    - a `directness: "direct"` item's `quote` is a real, whitespace-
      normalized substring of that fragment's text - "не угадывать"
      (gap_search's own author-provenance rule), applied here to quotes.
    """
    by_id = {f.fragment_id: f for f in fetched}
    errors: List[EvidenceValidationError] = []
    for i, item in enumerate(items):
        fid = item.get("fragment_id")
        f = by_id.get(fid)
        if f is None:
            errors.append(EvidenceValidationError(i, "fragment_id", f"no fetched fragment with id {fid!r}"))
            continue
        if f.status != "resolved":
            errors.append(EvidenceValidationError(i, "fragment_id", f"fragment {fid!r} status is {f.status!r}, not resolved"))
            continue
        if item.get("directness") == "direct":
            quote = (item.get("quote") or "").strip()
            if not quote:
                errors.append(EvidenceValidationError(i, "quote", "directness=direct requires a non-empty quote"))
            else:
                norm_quote = " ".join(quote.split())
                norm_text = " ".join((f.text or "").split())
                if norm_quote not in norm_text:
                    errors.append(EvidenceValidationError(
                        i, "quote", f"quote not found verbatim in fragment {fid!r} text - do not paraphrase and label it a direct quote",
                    ))
        if not item.get("claim"):
            errors.append(EvidenceValidationError(i, "claim", "missing claim/question facet"))
    return errors


def read_cost_tokens(fragment: FetchedFragment) -> int:
    if not fragment.text:
        return 0
    return max(1, len(fragment.text) // CHARS_PER_TOKEN)
