#!/usr/bin/env python3
"""obsidian-author: turn settled research into new, structured Markdown articles.

Implements spec passport 04-obsidian-author.md (US-004), REQ-FND-0001
(global name uniqueness) and REQ-KNO-0001 (the two-sentence '## Суть').
This script only ever *creates* files - an existing file with the same
resolved name is a hard conflict, not something it updates (that's
obsidian-revise's job; the two skills stay cleanly separated on purpose).

Subcommands
-----------
  check-name   - REQ-FND-0001 uniqueness check, before you've even drafted
                 a body; call this first for every candidate title.
  skeleton     - print the section skeleton for a note type (A2 default).
  new          - assemble frontmatter + '## Суть' + body into a draft.
                 Defaults to a dry run (prints what would be written);
                 pass --apply to actually create the file.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path, PurePosixPath
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import linkgraph, markdown as md, pathutil  # noqa: E402
from obsidian_common import patch as p  # noqa: E402
from obsidian_common.frontmatter_ops import serialize_frontmatter  # noqa: E402
from obsidian_common.profile import ProfileError, VaultProfile, resolve_profile  # noqa: E402

SKELETONS = {
    "concept": "## Как это работает\n\n...\n\n## Пример\n\n...\n\n## Related\n\n- \n\n## Sources\n\n- \n",
    "method": "## Шаги\n\n1. ...\n\n## Когда применять\n\n...\n\n## Related\n\n- \n\n## Sources\n\n- \n",
    "comparison": "## Варианты\n\n### Вариант A\n\n...\n\n### Вариант B\n\n...\n\n## Вывод\n\n...\n\n## Sources\n\n- \n",
    "guide": "## Предпосылки\n\n...\n\n## Шаги\n\n1. ...\n\n## Related\n\n- \n",
    "reference": "## Содержание\n\n...\n\n## Sources\n\n- \n",
    "source": "## О чём публикация\n\n...\n\n## Ключевые тезисы\n\n- \n",
    "research": "## Находки\n\n- \n\n## Related\n\n- \n\n## Sources\n\n- \n",
}


def cmd_skeleton(args) -> int:
    skel = SKELETONS.get(args.type)
    if skel is None:
        print(f"No built-in skeleton for type={args.type!r}. Known: {list(SKELETONS)}", file=sys.stderr)
        return 2
    print(f"## Суть\n\n<первое предложение — центральная мысль>. <второе — механизм/применимость/следствие>.\n\n{skel}")
    return 0


def check_name(profile: VaultProfile, title: str, folder: str, batch_titles: List[str]) -> dict:
    desired = f"{title}.md"
    rel_candidate = f"{folder.rstrip('/')}/{desired}" if folder else desired
    key = pathutil.normalize_basename(desired)

    index = linkgraph.build_basename_index(profile.vault_path, profile.scope)
    vault_collisions = index.get(pathutil.normalize_basename(title), [])

    batch_collisions = [
        t for t in batch_titles
        if pathutil.normalize_basename(f"{t}.md") == key and t != title
    ]

    exists_exact = (Path(profile.vault_path) / rel_candidate).is_file()

    return {
        "title": title,
        "candidate_path": rel_candidate,
        "exists_exact_path": exists_exact,
        "vault_wide_basename_collisions": vault_collisions,
        "batch_collisions": batch_collisions,
        "unique": exists_exact is False and not vault_collisions and not batch_collisions,
        "project_codes_available": profile.naming.project_codes,
    }


def cmd_check_name(args, profile: VaultProfile) -> int:
    batch = [t.strip() for t in (args.batch_titles or "").split(",") if t.strip()]
    result = check_name(profile, args.title, args.folder or "", batch)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    if not result["unique"]:
        print(
            "\nNot unique. Apply a project code before the basename (keep "
            f"MOC_/HUB_ first if navigational): {result['project_codes_available'] or '(none configured in profile.naming.project_codes)'}",
            file=sys.stderr,
        )
        return 1
    return 0


def cmd_new(args, profile: VaultProfile) -> int:
    batch = [t.strip() for t in (args.batch_titles or "").split(",") if t.strip()]
    name_check = check_name(profile, args.title, args.folder, batch)
    if not name_check["unique"]:
        print("error: name is not unique - run check-name and apply a project code first", file=sys.stderr)
        print(json.dumps(name_check, ensure_ascii=False, indent=2, default=str), file=sys.stderr)
        return 2

    suti = args.suti.strip()
    n_sentences = md.count_sentences(suti)
    if n_sentences != 2:
        print(
            f"warning: '## Суть' looks like {n_sentences} sentence(s), REQ-KNO-0001 wants exactly 2 "
            "(heuristic count - a real abbreviation/ellipsis can throw it off; double-check by eye)",
            file=sys.stderr,
        )

    body = ""
    if args.body_file:
        body = Path(args.body_file).read_text(encoding="utf-8")

    today = dt.date.today().isoformat()
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    aliases = [a.strip() for a in (args.aliases or "").split(",") if a.strip()]
    meta = {
        "type": args.type,
        "status": "draft",
        "tags": tags,
        "created": today,
        "updated": today,
    }
    if aliases:
        meta["aliases"] = aliases
    if args.summary:
        meta["summary"] = args.summary
    for field_name, cli_val in (("topics", args.topics), ("sources", args.sources), ("moc", args.moc)):
        if cli_val:
            meta[field_name] = [v.strip() for v in cli_val.split(",") if v.strip()]

    content = serialize_frontmatter(meta) + f"\n## Суть\n\n{suti}\n\n{body.strip()}\n"
    rel_path = name_check["candidate_path"]

    if not args.apply:
        print(f"[dry run] would create: {rel_path}\n")
        print(content)
        print("\n(pass --apply to actually write this file)")
        return 0

    try:
        patch = p.propose_create_file(profile.vault_path, rel_path, content,
                                       reason="obsidian-author: new article")
    except p.PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    record = p.apply_patch(profile.vault_path, patch)
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, default=str))
    if record.status == "applied":
        print(
            f"\nWritten: {rel_path}\nindex_dirty: obsidian-index-sync (skill 18) is not built in this "
            "project yet - the semantic index, if any, does not know about this file.",
            file=sys.stderr,
        )
    return 0 if record.status == "applied" else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help="profile file path or registered vault id")
    sub = ap.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check-name", help="REQ-FND-0001 global uniqueness check")
    p_check.add_argument("--title", required=True)
    p_check.add_argument("--folder", default="")
    p_check.add_argument("--batch-titles", help="comma list of other titles being created in the same pass")

    p_skel = sub.add_parser("skeleton", help="print the section skeleton for a note type")
    p_skel.add_argument("--type", required=True, choices=list(SKELETONS))

    p_new = sub.add_parser("new", help="assemble and (optionally) write a new draft article")
    p_new.add_argument("--title", required=True)
    p_new.add_argument("--type", required=True)
    p_new.add_argument("--folder", help="defaults to the profile's managed_folders.drafts")
    p_new.add_argument("--suti", required=True, help="the two-sentence '## Суть' text")
    p_new.add_argument("--body-file", help="Markdown file with everything after '## Суть'")
    p_new.add_argument("--tags")
    p_new.add_argument("--aliases")
    p_new.add_argument("--summary")
    p_new.add_argument("--topics")
    p_new.add_argument("--sources")
    p_new.add_argument("--moc")
    p_new.add_argument("--batch-titles")
    p_new.add_argument("--apply", action="store_true")

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "check-name":
        return cmd_check_name(args, profile)
    if args.command == "skeleton":
        return cmd_skeleton(args)
    if args.command == "new":
        if not args.folder:
            args.folder = profile.managed_folders.drafts
        return cmd_new(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
