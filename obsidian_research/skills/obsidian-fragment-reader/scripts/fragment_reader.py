#!/usr/bin/env python3
"""obsidian-fragment-reader: addressed reading of one paragraph, block,
line range, section, or section-plus-children - never a whole article
unless you actually ask for one.

Implements spec passport 15-obsidian-fragment-reader.md (US-002, US-011).
This is the shared primitive `obsidian-research`, `obsidian-revise`,
`obsidian-link`, `obsidian-moc` and `obsidian-hub` all build their own
addressed reads on top of (`lib/obsidian_common/markdown.py`'s
`read_fragment`) - this skill is that capability exposed directly, for
when the caller just needs to read something specific without going
through one of those other skills' own workflow.

Subcommands
-----------
  read     - address by --heading, --block-id, or --line-range (exactly
             one; --heading wins if more than one is given by mistake).
  preview  - the new-article '## Суть' shortcut (rule 8): missing is a
             normal, expected outcome for an older note, not an error.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import markdown as md  # noqa: E402
from obsidian_common.pathutil import is_excluded  # noqa: E402
from obsidian_common.profile import ProfileError, resolve_profile  # noqa: E402


def _result_dict(r: md.FragmentResult) -> dict:
    return {
        "status": r.status,
        "path": r.path,
        "heading_path": r.heading_path,
        "line_start": r.line_start,
        "line_end": r.line_end,
        "content_hash": r.content_hash,
        "candidates": r.candidates,
        "truncated": r.truncated,
        "callouts": [
            {"type": c.type, "title": c.title, "text": c.text,
             "line_start": c.line_start, "line_end": c.line_end}
            for c in r.callouts
        ],
        "internal_refs_outside_range": r.internal_refs_outside_range,
        "text": r.text,
    }


def _print(r: md.FragmentResult, fmt: str) -> int:
    d = _result_dict(r)
    if fmt == "json":
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
        return 0 if r.status == "resolved" else 1
    print(f"status={r.status}  path={r.path}  heading_path={r.heading_path}  "
          f"lines={r.line_start}-{r.line_end}  hash={r.content_hash}")
    if r.candidates:
        print("candidates:")
        for c in r.candidates:
            print(f"  - {c}")
    if r.callouts:
        print(f"callouts ({len(r.callouts)}):")
        for c in r.callouts:
            print(f"  [{c.type}] {c.title}: {c.text[:80]}")
    if r.internal_refs_outside_range:
        print("internal_refs_outside_range (same-file links pointing outside this "
              "fragment - read them separately if the fragment doesn't make sense "
              "without them):", r.internal_refs_outside_range)
    if r.truncated:
        print("⚠️ truncated to --max-chars")
    if r.text is not None:
        print("---")
        print(r.text)
    return 0 if r.status == "resolved" else 1


def cmd_read(args, profile) -> int:
    if is_excluded(args.path, profile.scope):
        r = md.FragmentResult("out_of_scope", args.path, None, None, None, None, None)
        return _print(r, args.format)

    line_range = None
    if args.line_range:
        try:
            a, b = args.line_range.split("-", 1)
            line_range = (int(a), int(b) + 1)  # CLI end is inclusive; read_fragment's is exclusive
        except ValueError:
            print("error: --line-range must be START-END, e.g. 10-20", file=sys.stderr)
            return 2

    r = md.read_fragment(
        profile.vault_path, args.path,
        heading_query=args.heading,
        block_id=args.block_id,
        line_range=line_range,
        include_children=args.include_children,
        child_depth=args.child_depth,
        max_chars=args.max_chars,
    )
    if r.status == "needs_context":
        print("Ambiguous - more than one heading matches. Disambiguate with "
              "'Parent > Child' (see candidates) rather than guessing.", file=sys.stderr)
    return _print(r, args.format)


def cmd_preview(args, profile) -> int:
    r = md.read_fragment(profile.vault_path, args.path, heading_query="Суть")
    if r.status == "not_found":
        print(json.dumps({
            "path": args.path, "status": "no_suti",
            "note": "No '## Суть' section - normal for a note that predates REQ-KNO-0001, "
                    "not a reading error. Fall back to normal progressive retrieval "
                    "(metadata summary, then addressed sections) for this note.",
        }, ensure_ascii=False, indent=2))
        return 0
    n = md.count_sentences(r.text or "") if r.text else 0
    if args.format == "json":
        d = _result_dict(r)
        d["sentence_count_heuristic"] = n
        print(json.dumps(d, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"## Суть ({n} heuristic sentence(s), REQ-KNO-0001 wants exactly 2)\n")
        print(r.text)
    return 0 if r.status == "resolved" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help="profile file path or registered vault id")
    ap.add_argument("--format", default="md", choices=["md", "json"])
    sub = ap.add_subparsers(dest="command", required=True)

    p_read = sub.add_parser("read", help="addressed read by heading, block id, or line range")
    p_read.add_argument("--path", required=True)
    p_read.add_argument("--heading", help="exact heading title, or 'Parent > Child' to disambiguate duplicates")
    p_read.add_argument("--block-id", help="Obsidian ^blockid, without the caret")
    p_read.add_argument("--line-range", help="START-END, 1-indexed, both inclusive, e.g. 42-58")
    p_read.add_argument("--include-children", action="store_true",
                         help="with --heading: also include descendant subsections")
    p_read.add_argument("--child-depth", type=int, default=1,
                         help="how many levels of descendants --include-children adds (default 1)")
    p_read.add_argument("--max-chars", type=int, help="truncate returned text to this many characters")

    p_prev = sub.add_parser("preview", help="REQ-KNO-0001 '## Суть' shortcut; missing is not an error")
    p_prev.add_argument("--path", required=True)

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "read":
        if not (args.heading or args.block_id or args.line_range):
            print("error: give exactly one of --heading, --block-id, --line-range "
                  "(omit all three to read section-less whole file - rare, prefer a real address)",
                  file=sys.stderr)
            return 2
        return cmd_read(args, profile)
    if args.command == "preview":
        return cmd_preview(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
