#!/usr/bin/env python3
"""obsidian-semantic-search: RAPTOR semantic retrieval over the Qdrant
index obsidian-index-sync builds - search by meaning across article/
section/subsection/chunk/callout levels, not by keyword.

Implements spec passport 13-obsidian-semantic-search.md (US-011/US-014).
The actual query/expand logic lives in lib/obsidian_common/semantic.py;
this script is the CLI surface (arg parsing, formatting) only.

Subcommands
-----------
  search  - embed a query, return top-k RaptorMatch[] ranked by cosine
            similarity. Defaults to the "summary" vector space (covers
            every node level); --using raw searches only section/
            subsection/article nodes small enough to have a raw-text
            vector too (see raptor.should_embed_raw).
  expand  - given node IDs (from a search hit's child_ids/parent_id),
            fetch those nodes directly by ID - no new similarity search.
            The progressive-disclosure step: "this section matched well,
            show me its actual chunks" or "show me the section this chunk
            belongs to".

Never returns node text - only source_path + line range + heading_path
(and a short preview). Read the actual text with obsidian-fragment-reader
using that address; a summary vector matching a query is a *pointer* to
real text, never presented as the evidence itself (foundation.md:
"исходный Markdown - источник истины").
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import semantic  # noqa: E402
from obsidian_common.embeddings import EmbeddingUnavailable  # noqa: E402
from obsidian_common.profile import ProfileError, resolve_profile  # noqa: E402
from obsidian_common.vectorstore import VectorStoreUnavailable  # noqa: E402


def _print_matches(matches: List[semantic.RaptorMatch], fmt: str, degraded: str = "") -> int:
    if fmt == "json":
        print(json.dumps({
            "matches": [asdict(m) for m in matches],
            "degraded": degraded or None,
        }, ensure_ascii=False, indent=2))
        return 0
    if degraded:
        print(f"⚠️ {degraded}\n")
    if not matches:
        print("No matches.")
        return 0
    for m in matches:
        print(f"{m.score:.3f}  [{m.node_level}]  {m.source_path}")
        if m.heading_path:
            print(f"        heading_path: {' > '.join(m.heading_path)}")
        print(f"        lines {m.line_start}-{m.line_end}  node_id={m.node_id}  "
              f"vector={m.vector_used}  summary_source={m.summary_source}")
        print(f"        {m.preview}")
        if m.child_ids:
            print(f"        child_ids: {m.child_ids}")
        print()
    return 0


def cmd_search(args, profile) -> int:
    try:
        matches = semantic.search(
            profile, args.query, top_k=args.top_k,
            node_levels=args.node_levels, using=args.using,
        )
    except EmbeddingUnavailable as exc:
        return _print_matches([], args.format, degraded=f"embeddings_unavailable: {exc}") or 1
    except VectorStoreUnavailable as exc:
        return _print_matches([], args.format, degraded=f"vectorstore_unavailable: {exc}") or 1
    return _print_matches(matches, args.format)


def cmd_expand(args, profile) -> int:
    try:
        matches = semantic.expand(profile, args.node_ids)
    except VectorStoreUnavailable as exc:
        return _print_matches([], args.format, degraded=f"vectorstore_unavailable: {exc}") or 1
    return _print_matches(matches, args.format)


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="profile file path or registered vault id")
    common.add_argument("--format", default="md", choices=["md", "json"])

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="embed a query, return top-k ranked matches", parents=[common])
    p_search.add_argument("--query", required=True)
    p_search.add_argument("--top-k", type=int, default=10)
    p_search.add_argument("--node-levels", nargs="+", choices=["article", "section", "subsection", "chunk", "callout"],
                           help="restrict to these node levels (default: all)")
    p_search.add_argument("--using", default="summary", choices=["summary", "raw"],
                           help="which named vector space to search (default: summary, covers every node)")

    p_expand = sub.add_parser("expand", help="fetch specific nodes by ID (no similarity search)", parents=[common])
    p_expand.add_argument("--node-ids", nargs="+", required=True)

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "search":
        return cmd_search(args, profile)
    if args.command == "expand":
        return cmd_expand(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
