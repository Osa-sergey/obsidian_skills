#!/usr/bin/env python3
"""obsidian-retrieve: hybrid retrieval orchestrator - combines Omnisearch
(keyword), RAPTOR semantic search, and MOC/graph proximity into one
deduplicated, budget-aware CandidateSet.

Implements spec passport 14-obsidian-retrieve.md (US-002/US-011). The
actual orchestration lives in lib/obsidian_common/retrieve.py; this
script is the CLI surface only.

Honest scope note: Dataview/Bases pre-filter (skills 11/12) is not
implemented here - this runs Omnisearch + semantic search + graph
expansion (deep mode only) and says so in `retrievers_used`, never
silently pretends a pre-filter step happened.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import retrieve  # noqa: E402
from obsidian_common.profile import ProfileError, resolve_profile  # noqa: E402


def _candidate_dict(c: retrieve.Candidate) -> dict:
    d = {
        "source_path": c.source_path,
        "reasons": c.reasons,
        "omnisearch_score": c.omnisearch_score,
        "omnisearch_excerpt": c.omnisearch_excerpt,
        "semantic_score": c.semantic_score,
        "graph_distance": c.graph_distance,
        "graph_direction": c.graph_direction,
        "combined_score": c.combined_score,
        "estimated_read_tokens": c.estimated_read_tokens,
    }
    if c.semantic_match:
        m = c.semantic_match
        d["semantic_match"] = {
            "node_id": m.node_id, "node_level": m.node_level, "heading_path": m.heading_path,
            "line_start": m.line_start, "line_end": m.line_end, "preview": m.preview,
            "summary_source": m.summary_source,
        }
    return d


def _print(result: retrieve.CandidateSetResult, fmt: str) -> int:
    if fmt == "json":
        print(json.dumps({
            "mode": result.mode,
            "retrievers_used": result.retrievers_used,
            "retrievers_skipped": result.retrievers_skipped,
            "vault_mismatch_warning": result.vault_mismatch_warning,
            "budget_max_tokens": result.budget_max_tokens,
            "budget_used_tokens": result.budget_used_tokens,
            "budget_truncated": result.budget_truncated,
            "candidates": [_candidate_dict(c) for c in result.candidates],
            "recommendations": result.recommendations,
        }, ensure_ascii=False, indent=2))
        return 0

    print(f"mode={result.mode}  retrievers_used={result.retrievers_used}")
    if result.retrievers_skipped:
        for name, reason in result.retrievers_skipped.items():
            print(f"⚠️ {name} skipped: {reason}")
    if result.vault_mismatch_warning:
        print(f"⚠️ vault_mismatch: {result.vault_mismatch_warning}")
    print(f"budget: {result.budget_used_tokens}/{result.budget_max_tokens} tokens"
          f"{'  (truncated)' if result.budget_truncated else ''}")
    print()
    for c in result.candidates:
        print(f"{c.combined_score:.3f}  {c.source_path}  reasons={c.reasons}")
        if c.semantic_match:
            m = c.semantic_match
            hp = " > ".join(m.heading_path) or "(article root)"
            print(f"        semantic: {hp}  lines {m.line_start}-{m.line_end}  {m.preview[:80]}")
        if c.omnisearch_excerpt:
            print(f"        omnisearch: {c.omnisearch_excerpt[:100]}")
        if c.graph_distance is not None:
            print(f"        graph: depth={c.graph_distance} via {c.graph_direction}")
    print()
    for r in result.recommendations:
        print(f"- {r}")
    return 0


def cmd_search(args, profile) -> int:
    result = retrieve.build_candidate_set(profile, args.query, mode=args.mode, top_k=args.top_k)
    return _print(result, args.format)


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="profile file path or registered vault id")
    common.add_argument("--format", default="md", choices=["md", "json"])

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="run the hybrid retrieval pipeline", parents=[common])
    p_search.add_argument("--query", nargs="+", required=True, help="one or more query formulations")
    p_search.add_argument("--mode", default="narrow", choices=["narrow", "deep"])
    p_search.add_argument("--top-k", type=int, default=10, help="per-query semantic search top-k before merging")

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "search":
        return cmd_search(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
