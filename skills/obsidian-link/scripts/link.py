#!/usr/bin/env python3
"""obsidian-link: find broken links and propose/apply cross-links between
existing articles.

Implements spec passport 06-obsidian-link.md (US-006). Relationship
judgment (does A really "clarify" B?) is Claude's job - this script
handles what's mechanical: does a link already exist (idempotency),
building the right wikilink syntax for the chosen granularity (article /
heading / block, L4), and writing the insertion safely through the same
propose/apply engine `obsidian-revise` uses (`lib/obsidian_common/patch.py`).

Subcommands
-----------
  find-broken     - scope-wide report of unresolved/ambiguous wikilinks.
  check-existing  - does `source` already link to `target` in any form?
  propose         - build a patch that adds a link (Related-section or,
                    for a block-level target, assigns a ^block-id first).
  apply           - same apply engine as obsidian-revise.

Inline, in-prose link insertion (rewriting a sentence to *contain* the new
wikilink) is intentionally NOT a separate operation here - that is prose
editing, i.e. `obsidian-revise propose --op replace-section`. This script
covers Related-section placement and block/heading anchoring only.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import linkgraph, markdown as md  # noqa: E402
from obsidian_common import patch as p  # noqa: E402
from obsidian_common.profile import ProfileError, resolve_profile  # noqa: E402

L5_SOFT_CAP = 5  # defaults.md §11: up to 5 new auto-suggested links per article per pass


def cmd_find_broken(args, profile) -> int:
    scope = profile.scope
    basename_index = linkgraph.build_basename_index(profile.vault_path, scope)
    forward = linkgraph.build_forward_index(profile.vault_path, scope, basename_index)

    broken = []
    for source, edges in forward.items():
        if args.scope and not source.startswith(args.scope.strip("/")):
            continue
        for edge in edges:
            if edge.target is None:
                broken.append({
                    "source": source, "target_raw": edge.target_raw, "kind": edge.kind,
                    "reason": "ambiguous" if edge.ambiguous_candidates else "not_found",
                    "candidates": edge.ambiguous_candidates,
                })
    print(json.dumps({"scope": args.scope or "(whole vault)", "count": len(broken), "broken": broken},
                      ensure_ascii=False, indent=2, default=str))
    return 0


def _existing_edges(profile, source_rel: str, target_rel: str):
    basename_index = linkgraph.build_basename_index(profile.vault_path, profile.scope)
    edges = linkgraph.extract_edges_from_file(profile.vault_path, source_rel, basename_index)
    return [e for e in edges if e.target == target_rel]


def cmd_check_existing(args, profile) -> int:
    matches = _existing_edges(profile, args.source, args.target)
    result = {
        "source": args.source, "target": args.target,
        "already_linked": len(matches) > 0,
        "edges": [{"kind": e.kind, "target_raw": e.target_raw, "anchor": e.anchor} for e in matches],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def _link_markdown(target_path: str, heading: str = None, block_id: str = None, alias: str = None) -> str:
    inner = target_path[:-3] if target_path.endswith(".md") else target_path
    if block_id:
        inner += f"#^{block_id}"
    elif heading:
        inner += f"#{heading}"
    if alias:
        return f"[[{inner}|{alias}]]"
    return f"[[{inner}]]"


def cmd_propose(args, profile) -> int:
    vocab = profile.vocab.get("link_relations", [])
    if args.relation not in vocab:
        print(f"warning: relation {args.relation!r} is not in this vault's controlled vocabulary "
              f"({vocab}) - proceeding, but consider adding an explanation", file=sys.stderr)

    existing = _existing_edges(profile, args.source, args.target)
    if existing and not args.force:
        print(json.dumps({
            "status": "already_linked", "source": args.source, "target": args.target,
            "edges": [{"kind": e.kind, "anchor": e.anchor} for e in existing],
        }, ensure_ascii=False, indent=2, default=str))
        return 1

    if args.existing_new_links_count >= L5_SOFT_CAP:
        print(f"warning: {args.existing_new_links_count} new links already proposed for "
              f"{args.source!r} this pass - L5 default cap is {L5_SOFT_CAP}; make sure this one "
              "is worth exceeding it", file=sys.stderr)

    block_id = None
    if args.granularity == "block":
        try:
            bid_patch = p.propose_ensure_block_id(
                profile.vault_path, args.target, args.target_heading, args.target_paragraph,
                reason=f"anchor for a link from {args.source}",
            )
        except p.PatchError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
        if bid_patch.based_on is None:
            block_id = bid_patch.params["existing_id"]
        else:
            rec = p.apply_patch(profile.vault_path, bid_patch) if args.apply else None
            if rec and rec.status not in ("applied", "unchanged"):
                print(json.dumps(rec.to_dict(), ensure_ascii=False, indent=2, default=str), file=sys.stderr)
                return 1
            block_id = bid_patch.params.get("new_id") or bid_patch.params.get("existing_id")
            if not args.apply:
                print("[dry run] would first assign a block id on the target:")
                print(bid_patch.preview_diff)

    link_md = _link_markdown(
        args.target,
        heading=args.target_heading if args.granularity == "heading" else None,
        block_id=block_id,
        alias=args.alias,
    )
    bullet = f"- {link_md} — {args.reason}" if args.reason else f"- {link_md}"

    try:
        patch = p.propose_append_section(
            profile.vault_path, args.source, args.related_heading, bullet,
            create_if_missing=True, reason=f"{args.relation}: {args.reason or ''}".strip(": "),
            sources=[args.target],
        )
    except p.PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out = patch.to_json()
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"proposal written: {args.out}")
    print("\n--- diff preview ---")
    print(patch.preview_diff)
    if not args.out:
        print("\n--- full proposal JSON (save this, 'apply' needs it) ---")
        print(out)
    return 0


def cmd_apply(args, profile) -> int:
    patch = p.Patch.from_json(Path(args.proposal).read_text(encoding="utf-8"))
    record = p.apply_patch(profile.vault_path, patch)
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, default=str))
    if record.status == "applied":
        print("\nindex_dirty: obsidian-index-sync (skill 18) is not built in this project yet.",
              file=sys.stderr)
    return 0 if record.status in ("applied", "unchanged") else 1


def main() -> int:
    # --profile is defined on each subparser (via parents=), not the top
    # level - see workflow.py's main() for why ("script.py subcommand
    # --profile X" must work, not only "script.py --profile X subcommand").
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="profile file path or registered vault id")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_fb = sub.add_parser("find-broken", help="report unresolved/ambiguous wikilinks in scope", parents=[common])
    p_fb.add_argument("--scope", help="vault-relative folder prefix; omit for the whole vault")

    p_ce = sub.add_parser("check-existing", help="does source already link to target?", parents=[common])
    p_ce.add_argument("--source", required=True)
    p_ce.add_argument("--target", required=True)

    p_pr = sub.add_parser("propose", help="propose adding a cross-link from source to target", parents=[common])
    p_pr.add_argument("--source", required=True)
    p_pr.add_argument("--target", required=True)
    p_pr.add_argument("--relation", required=True,
                       help="prerequisite/clarifies/applies/example/alternative/contradicts/derived-from (L2)")
    p_pr.add_argument("--reason", required=True, help="one line explaining why this link is useful (acceptance.md: 'a shared tag is not enough')")
    p_pr.add_argument("--granularity", default="article", choices=["article", "heading", "block"])
    p_pr.add_argument("--target-heading", help="required for granularity=heading, or heading containing the paragraph for granularity=block")
    p_pr.add_argument("--target-paragraph", help="required for granularity=block: exact substring identifying the paragraph")
    p_pr.add_argument("--alias", help="display alias for the wikilink")
    p_pr.add_argument("--related-heading", default="Related", help="section to append the link to (L3 default)")
    p_pr.add_argument("--existing-new-links-count", type=int, default=0,
                       help="how many new links you've already proposed for --source this pass (L5 cap check)")
    p_pr.add_argument("--force", action="store_true", help="propose even if check-existing would say already_linked")
    p_pr.add_argument("--apply", action="store_true", help="also apply the block-id sub-step immediately (granularity=block only)")
    p_pr.add_argument("--out", help="save the proposal JSON here instead of printing it")

    p_ap = sub.add_parser("apply", help="re-check freshness and write a previously proposed link patch", parents=[common])
    p_ap.add_argument("--proposal", required=True)

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "find-broken":
        return cmd_find_broken(args, profile)
    if args.command == "check-existing":
        return cmd_check_existing(args, profile)
    if args.command == "propose":
        if args.granularity == "heading" and not args.target_heading:
            print("error: --granularity heading requires --target-heading", file=sys.stderr)
            return 2
        if args.granularity == "block" and not (args.target_heading and args.target_paragraph):
            print("error: --granularity block requires --target-heading and --target-paragraph", file=sys.stderr)
            return 2
        return cmd_propose(args, profile)
    if args.command == "apply":
        return cmd_apply(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
