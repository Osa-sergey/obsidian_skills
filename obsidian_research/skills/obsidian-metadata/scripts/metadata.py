#!/usr/bin/env python3
"""obsidian-metadata: validate, normalize, and propose YAML frontmatter.

Implements spec passport 07-obsidian-metadata.md (US-010). Backed by
`lib/obsidian_common/frontmatter_ops.py` (additive merge, stable
serialization) and `patch.py` (the same safe apply engine as
obsidian-revise) - `propose`/`apply` here are `yaml-merge` with metadata-
specific validation run first, not a different write mechanism.

Subcommands
-----------
  validate      - check a file's frontmatter against the vault's controlled
                  vocabulary (M2) and required core fields (M4). Warnings
                  only - an unknown type/status is flagged, never rejected
                  or silently coerced (M1).
  check-tag     - is a proposed tag a near-duplicate of one already used in
                  the vault (case/punctuation variant)?
  list-vocab    - print this vault's controlled types/statuses/relations.
  propose       - validate, then build a yaml-merge patch (additive).
  apply         - same apply engine as obsidian-revise.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import linkgraph, markdown as md  # noqa: E402
from obsidian_common import patch as p  # noqa: E402
from obsidian_common.frontmatter_ops import (  # noqa: E402
    suggest_tag_canonicalization, validate_frontmatter,
)
from obsidian_common.profile import ProfileError, resolve_profile  # noqa: E402


def cmd_validate(args, profile) -> int:
    full = Path(profile.vault_path) / args.path
    if not full.is_file():
        print(f"error: not_found: {args.path}", file=sys.stderr)
        return 2
    raw = md.read_text(full)
    parsed = md.parse_frontmatter(raw)
    if parsed.meta_error:
        print(json.dumps({"path": args.path, "error": parsed.meta_error}, ensure_ascii=False, indent=2, default=str))
        return 1

    required = [f.strip() for f in args.required.split(",")] if args.required else None
    issues = validate_frontmatter(parsed.meta, vocab=profile.vocab, required_fields=required)
    result = {
        "path": args.path,
        "meta": parsed.meta,
        "issues": [{"field": i.field, "severity": i.severity, "message": i.message} for i in issues],
        "ok": len(issues) == 0,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


def _all_vault_tags(profile) -> set:
    tags = set()
    for rel in linkgraph.iter_vault_files(profile.vault_path, profile.scope, extensions={".md"}):
        raw = md.read_text(Path(profile.vault_path) / rel)
        meta = md.parse_frontmatter(raw).meta
        t = meta.get("tags")
        if isinstance(t, list):
            tags.update(str(x) for x in t)
        elif isinstance(t, str):
            tags.add(t)
    return tags


def cmd_check_tag(args, profile) -> int:
    existing = _all_vault_tags(profile)
    suggestion = suggest_tag_canonicalization(args.tag, list(existing))
    result = {
        "proposed_tag": args.tag,
        "existing_close_match": suggestion,
        "recommendation": (
            f"reuse existing tag {suggestion!r} instead of adding a near-duplicate"
            if suggestion else "no close match found in the vault - safe to propose as a new tag"
        ),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_list_vocab(args, profile) -> int:
    print(json.dumps({
        "vocab": profile.vocab,
        "managed_folders": {
            "drafts": profile.managed_folders.drafts, "sources": profile.managed_folders.sources,
            "moc": profile.managed_folders.moc, "hub": profile.managed_folders.hub,
            "research": profile.managed_folders.research,
        },
        "naming": {"moc_prefix": profile.naming.moc_prefix, "hub_prefix": profile.naming.hub_prefix,
                   "project_codes": profile.naming.project_codes},
    }, ensure_ascii=False, indent=2, default=str))
    return 0


def cmd_propose(args, profile) -> int:
    updates = json.loads(Path(args.updates_file).read_text(encoding="utf-8"))

    full = Path(profile.vault_path) / args.path
    if full.is_file():
        raw = md.read_text(full)
        current = md.parse_frontmatter(raw).meta
    else:
        current = {}
    preview_merged = {**current, **updates}
    issues = validate_frontmatter(preview_merged, vocab=profile.vocab)
    if issues:
        print("Validation warnings on the merged result (not blocking, review before applying):", file=sys.stderr)
        for i in issues:
            print(f"  [{i.severity}] {i.field}: {i.message}", file=sys.stderr)

    try:
        patch = p.propose_yaml_merge(profile.vault_path, args.path, updates,
                                      reason=args.reason or "obsidian-metadata: schema/tag update")
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

    p_val = sub.add_parser("validate", help="check frontmatter against the vault's controlled vocabulary", parents=[common])
    p_val.add_argument("--path", required=True)
    p_val.add_argument("--required", help="comma list overriding the default required-field set")

    p_tag = sub.add_parser("check-tag", help="is this tag a near-duplicate of an existing one?", parents=[common])
    p_tag.add_argument("--tag", required=True)

    sub.add_parser("list-vocab", help="print this vault's controlled types/statuses/relations", parents=[common])

    p_prop = sub.add_parser("propose", help="validate, then build a yaml-merge patch", parents=[common])
    p_prop.add_argument("--path", required=True)
    p_prop.add_argument("--updates-file", required=True, help="JSON object of fields to merge (additive)")
    p_prop.add_argument("--reason")
    p_prop.add_argument("--out")

    p_ap = sub.add_parser("apply", help="re-check freshness and write a previously proposed patch", parents=[common])
    p_ap.add_argument("--proposal", required=True)

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "validate":
        return cmd_validate(args, profile)
    if args.command == "check-tag":
        return cmd_check_tag(args, profile)
    if args.command == "list-vocab":
        return cmd_list_vocab(args, profile)
    if args.command == "propose":
        return cmd_propose(args, profile)
    if args.command == "apply":
        return cmd_apply(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
