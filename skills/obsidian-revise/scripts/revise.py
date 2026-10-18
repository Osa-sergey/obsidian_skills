#!/usr/bin/env python3
"""obsidian-revise: propose and (on request) apply addressed edits to an
existing article.

Implements spec passport 05-obsidian-revise.md (US-005) and ADR-0002
(proposal-first). Every real edit goes through `lib/obsidian_common/patch.py`:
`propose` reads the live file, builds a diff, and remembers a hash of just
the touched region; `apply` re-reads, checks that region is unchanged, and
only then writes - a conflict is reported, not silently overwritten or
crashed on (see that module's docstring for why the check is scoped to the
region, not the whole file).

Subcommands
-----------
  propose        - one of --op replace-section / append-section /
                    managed-block / yaml-merge; prints (or saves) a Patch.
  apply           - re-reads, checks freshness, writes; prints a ChangeRecord.
  propose-rename  - REQ-FND-0001 uniqueness check + which files would need
                    their links updated. Informational only - U5 keeps
                    rename a proposal, this script does not execute one.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import linkgraph, pathutil  # noqa: E402
from obsidian_common import patch as p  # noqa: E402
from obsidian_common.profile import ProfileError, resolve_profile  # noqa: E402


def _sources_list(raw: str) -> list:
    return [s.strip() for s in (raw or "").split(",") if s.strip()]


def cmd_propose(args, profile) -> int:
    vault = profile.vault_path
    sources = _sources_list(args.sources)
    try:
        if args.op == "replace-section":
            new_text = Path(args.new_content_file).read_text(encoding="utf-8")
            patch = p.propose_replace_section(vault, args.path, args.heading, new_text,
                                               reason=args.reason or "", sources=sources)
        elif args.op == "append-section":
            addition = Path(args.new_content_file).read_text(encoding="utf-8")
            patch = p.propose_append_section(vault, args.path, args.heading, addition,
                                              create_if_missing=not args.no_create,
                                              reason=args.reason or "", sources=sources)
        elif args.op == "managed-block":
            body = Path(args.new_content_file).read_text(encoding="utf-8")
            patch = p.propose_managed_block(vault, args.path, args.block_id, body,
                                             skill_name="obsidian-revise",
                                             anchor_heading=args.heading,
                                             reason=args.reason or "", sources=sources)
        elif args.op == "yaml-merge":
            updates = json.loads(Path(args.updates_file).read_text(encoding="utf-8"))
            patch = p.propose_yaml_merge(vault, args.path, updates,
                                          reason=args.reason or "", sources=sources)
        else:
            print(f"error: unknown --op {args.op!r}", file=sys.stderr)
            return 2
    except p.PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    out = patch.to_json()
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
        print(f"proposal written: {args.out}")
    print("\n--- diff preview ---")
    print(patch.preview_diff or "(no textual diff - e.g. a fresh managed block insert)")
    if not args.out:
        print("\n--- full proposal JSON (save this, 'apply' needs it) ---")
        print(out)
    return 0


def cmd_apply(args, profile) -> int:
    patch = p.Patch.from_json(Path(args.proposal).read_text(encoding="utf-8"))
    record = p.apply_patch(profile.vault_path, patch)
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, default=str))
    if record.status == "applied":
        print(
            "\nindex_dirty: obsidian-index-sync (skill 18) is not built in this project yet - "
            "the semantic index, if any, does not reflect this change.",
            file=sys.stderr,
        )
    elif record.status == "conflict":
        print(
            "\nThe file changed since propose. Re-read it and call 'propose' again against the "
            "current content - do not retry 'apply' with the same proposal.",
            file=sys.stderr,
        )
    return 0 if record.status in ("applied", "unchanged") else 1


def cmd_propose_rename(args, profile) -> int:
    vault = profile.vault_path
    new_basename = PurePosixPath(args.new_name).name
    if not new_basename.endswith(".md"):
        new_basename += ".md"
    new_rel = str(PurePosixPath(args.path).parent / new_basename)

    index = linkgraph.build_basename_index(vault, profile.scope)
    collisions = index.get(pathutil.normalize_basename(PurePosixPath(new_rel).stem), [])
    collisions = [c for c in collisions if c != args.path]

    basename_idx = linkgraph.build_basename_index(vault, profile.scope)
    forward = linkgraph.build_forward_index(vault, profile.scope, basename_idx)
    backward = linkgraph.build_backward_index(forward)
    referencing = sorted({edge.source for edge in backward.get(args.path, [])})

    result = {
        "old_path": args.path,
        "proposed_new_path": new_rel,
        "unique": len(collisions) == 0,
        "name_collisions": collisions,
        "files_referencing_old_path": referencing,
        "note": (
            "Proposal only - this command does not rename the file or rewrite any "
            "links (U5). A human/explicit follow-up command must apply it; "
            "obsidian-index-sync would need to run afterward on both paths."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["unique"] else 1


def main() -> int:
    # --profile is defined on each subparser (via parents=), not the top
    # level - see workflow.py's main() for why ("script.py subcommand
    # --profile X" must work, not only "script.py --profile X subcommand").
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="profile file path or registered vault id")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_prop = sub.add_parser("propose", help="build a patch proposal (no write)", parents=[common])
    p_prop.add_argument("--path", required=True, help="vault-relative path of the existing article")
    p_prop.add_argument("--op", required=True,
                         choices=["replace-section", "append-section", "managed-block", "yaml-merge"])
    p_prop.add_argument("--heading", help="required for replace-section/append-section/managed-block")
    p_prop.add_argument("--block-id", help="required for managed-block")
    p_prop.add_argument("--new-content-file", help="required for replace-section/append-section/managed-block")
    p_prop.add_argument("--updates-file", help="required for yaml-merge: JSON object of fields to merge")
    p_prop.add_argument("--no-create", action="store_true", help="append-section: fail instead of creating a missing heading")
    p_prop.add_argument("--reason", help="why this edit (U2): fact fix, new confirmed fact, clarification, freshness, example, new link")
    p_prop.add_argument("--sources", help="comma list of source paths/URLs backing this edit")
    p_prop.add_argument("--out", help="save the proposal JSON here instead of printing it")

    p_apply = sub.add_parser("apply", help="re-check freshness and write a previously proposed patch", parents=[common])
    p_apply.add_argument("--proposal", required=True, help="path to a JSON file from 'propose --out'")

    p_ren = sub.add_parser("propose-rename", help="uniqueness + reverse-reference report only, no execution", parents=[common])
    p_ren.add_argument("--path", required=True)
    p_ren.add_argument("--new-name", required=True)

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "propose":
        required = {
            "replace-section": ["heading", "new_content_file"],
            "append-section": ["heading", "new_content_file"],
            "managed-block": ["heading", "block_id", "new_content_file"],
            "yaml-merge": ["updates_file"],
        }[args.op]
        missing = [r for r in required if getattr(args, r) is None]
        if missing:
            print(f"error: --op {args.op} requires: {', '.join('--' + m.replace('_', '-') for m in missing)}",
                  file=sys.stderr)
            return 2
        return cmd_propose(args, profile)
    if args.command == "apply":
        return cmd_apply(args, profile)
    if args.command == "propose-rename":
        return cmd_propose_rename(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
