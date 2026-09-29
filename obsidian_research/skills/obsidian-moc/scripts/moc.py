#!/usr/bin/env python3
"""obsidian-moc: create and grow hierarchical Maps of Content with an
explicit perspective.

Implements spec passport 08-obsidian-moc.md (US-007), ADR-0003 (one main
parent via `parent_mocs`, additional relations in `related_mocs`), and
REQ-FND-0001 (global name uniqueness, `MOC_` prefix). Reuses
`obsidian-author`'s create-with-uniqueness-check shape and
`lib/obsidian_common/patch.py`'s propose/apply engine for every write -
this script does not invent a second way to write a file safely.

Subcommands
-----------
  check-name      - REQ-FND-0001 uniqueness for a MOC_<Title>.md candidate.
  list-hierarchy  - discover every real MOC (type: moc in frontmatter, not
                    just filename) and its parent/child tree.
  check-cycle     - would assigning this parent create a cycle?
  new             - assemble frontmatter + Summary + Основные термины.
                    Dry run by default; --apply to write.
  add-article     - annotate an article into a MOC's article list AND set
                    the article's own `moc:` field (both sides, one call).
  add-child       - annotate a child MOC into a parent's list AND set the
                    child's `parent_mocs` (cycle-checked first).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import linkgraph, markdown as md, pathutil  # noqa: E402
from obsidian_common import patch as p  # noqa: E402
from obsidian_common.frontmatter_ops import serialize_frontmatter  # noqa: E402
from obsidian_common.profile import ProfileError, VaultProfile, resolve_profile  # noqa: E402

MOC_SKELETON = "## Дочерние MOC\n\n_нет_\n\n## Статьи\n\n_нет_\n"
_EMPTY_PLACEHOLDER = "_нет_"


def _propose_list_addition(vault_path, rel_path: str, heading: str, bullet: str, reason: str, sources: list) -> p.Patch:
    """append-section, except the very first real entry *replaces* the
    '_нет_' placeholder `new`/skeleton leaves behind instead of leaving it
    dangling next to the bullet - append-section's own idempotency (skip
    an addition already present) still applies from the second call on."""
    current = md.read_fragment(vault_path, rel_path, heading_query=heading)
    if current.status == "resolved":
        body = "\n".join(current.text.splitlines()[1:]).strip()
        if body == _EMPTY_PLACEHOLDER:
            return p.propose_replace_section(vault_path, rel_path, heading, f"## {heading}\n\n{bullet}\n",
                                              reason=reason, sources=sources)
    return p.propose_append_section(vault_path, rel_path, heading, bullet, create_if_missing=True,
                                     reason=reason, sources=sources)


def check_name(profile: VaultProfile, title: str, folder: str, batch_titles: List[str]) -> dict:
    desired = f"{profile.naming.moc_prefix}{title}.md"
    rel_candidate = f"{folder.rstrip('/')}/{desired}" if folder else desired
    key = pathutil.normalize_basename(desired)
    index = linkgraph.build_basename_index(profile.vault_path, profile.scope)
    vault_collisions = index.get(pathutil.normalize_basename(f"{profile.naming.moc_prefix}{title}"), [])
    batch_collisions = [
        t for t in batch_titles
        if pathutil.normalize_basename(f"{profile.naming.moc_prefix}{t}.md") == key and t != title
    ]
    exists_exact = (Path(profile.vault_path) / rel_candidate).is_file()
    return {
        "title": title, "candidate_path": rel_candidate, "exists_exact_path": exists_exact,
        "vault_wide_basename_collisions": vault_collisions, "batch_collisions": batch_collisions,
        "unique": exists_exact is False and not vault_collisions and not batch_collisions,
        "project_codes_available": profile.naming.project_codes,
    }


def discover_mocs(profile: VaultProfile) -> List[dict]:
    """Every file with `type: moc` in its own frontmatter - foundation.md
    §2.5 rule 5: a MOC_-looking filename alone never counts as proof."""
    basename_index = linkgraph.build_basename_index(profile.vault_path, profile.scope)
    out = []
    for rel in linkgraph.iter_vault_files(profile.vault_path, profile.scope, extensions={".md"}):
        raw = md.read_text(Path(profile.vault_path) / rel)
        meta = md.parse_frontmatter(raw).meta
        if meta.get("type") != "moc":
            continue
        parent_links = [
            fl.target for fl in md.extract_frontmatter_links(meta) if fl.field == "parent_mocs"
        ]
        parent_path = None
        if parent_links:
            resolved = linkgraph.resolve_link_target(profile.vault_path, parent_links[0], rel, basename_index)
            if resolved.status in ("resolved", "ambiguous"):
                parent_path = resolved.path
        out.append({
            "path": rel, "perspective": meta.get("perspective"),
            "perspective_question": meta.get("perspective_question"),
            "summary": meta.get("summary"), "parent_path": parent_path,
            "cls": pathutil.classify_navigation_name(PurePosixPath(rel).stem, profile.naming),
        })
    return out


def cmd_list_hierarchy(args, profile) -> int:
    mocs = discover_mocs(profile)
    by_path = {m["path"]: m for m in mocs}
    children: Dict[Optional[str], list] = {}
    for m in mocs:
        children.setdefault(m["parent_path"], []).append(m["path"])

    def render(path, depth, seen):
        if path in seen:
            print("  " * depth + f"⚠️ CYCLE at {path}")
            return
        seen = seen | {path}
        m = by_path.get(path)
        persp = f" [{m['perspective']}]" if m and m.get("perspective") else ""
        print("  " * depth + f"- {path}{persp}")
        for c in sorted(children.get(path, [])):
            render(c, depth + 1, seen)

    if args.format == "json":
        print(json.dumps({"mocs": mocs}, ensure_ascii=False, indent=2, default=str))
        return 0
    roots = sorted(children.get(None, []))
    if not roots and not mocs:
        print("No MOCs found (no file has `type: moc` in the connected vault/scope).")
        return 0
    for r in roots:
        render(r, 0, set())
    # MOCs whose declared parent doesn't resolve to a real MOC file
    orphaned = [m["path"] for m in mocs if m["parent_path"] and m["parent_path"] not in by_path]
    if orphaned:
        print("\n⚠️ parent_mocs points outside the discovered MOC set (broken or non-MOC target):")
        for o in orphaned:
            print(f"  - {o}")
    return 0


def would_create_cycle(profile: VaultProfile, moc_path: str, proposed_parent_path: str) -> bool:
    if moc_path == proposed_parent_path:
        return True
    by_path = {m["path"]: m for m in discover_mocs(profile)}
    current, seen = proposed_parent_path, set()
    while current:
        if current == moc_path:
            return True
        if current in seen:
            break  # a *pre-existing* cycle elsewhere - not this operation's to fix
        seen.add(current)
        current = by_path.get(current, {}).get("parent_path")
    return False


def cmd_check_cycle(args, profile) -> int:
    result = {
        "moc": args.moc, "proposed_parent": args.parent,
        "would_create_cycle": would_create_cycle(profile, args.moc, args.parent),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if result["would_create_cycle"] else 0


def cmd_check_name(args, profile) -> int:
    batch = [t.strip() for t in (args.batch_titles or "").split(",") if t.strip()]
    result = check_name(profile, args.title, args.folder or profile.managed_folders.moc, batch)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["unique"] else 1


def cmd_new(args, profile) -> int:
    folder = args.folder or profile.managed_folders.moc
    batch = [t.strip() for t in (args.batch_titles or "").split(",") if t.strip()]
    name_check = check_name(profile, args.title, folder, batch)
    if not name_check["unique"]:
        print("error: name is not unique - run check-name and apply a project code first", file=sys.stderr)
        print(json.dumps(name_check, ensure_ascii=False, indent=2, default=str), file=sys.stderr)
        return 2

    parent_mocs = []
    if args.parent:
        if not (Path(profile.vault_path) / args.parent).is_file():
            print(f"error: --parent {args.parent!r} does not exist", file=sys.stderr)
            return 2
        parent_meta = md.parse_frontmatter(md.read_text(Path(profile.vault_path) / args.parent)).meta
        if parent_meta.get("type") != "moc":
            print(f"error: --parent {args.parent!r} does not have type: moc", file=sys.stderr)
            return 2
        parent_mocs = [f"[[{args.parent[:-3]}]]"]

    today = dt.date.today().isoformat()
    terms = [t.strip() for t in (args.terms or "").split(",") if t.strip()]
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    meta = {
        "type": "moc", "status": "draft",
        "perspective": args.perspective, "perspective_question": args.perspective_question,
        "summary": args.summary, "terms": terms, "parent_mocs": parent_mocs,
        "tags": tags, "created": today, "updated": today,
    }
    summary_body = args.summary
    terms_body = "\n".join(f"- {t}" for t in terms) if terms else "_нет_"
    body = (
        f"\n## Summary\n\n{summary_body}\n\n"
        f"## Основные термины\n\n{terms_body}\n\n"
        f"{MOC_SKELETON}"
    )
    content = serialize_frontmatter(meta) + body
    rel_path = name_check["candidate_path"]

    if not args.apply:
        print(f"[dry run] would create: {rel_path}\n")
        print(content)
        return 0

    try:
        patch = p.propose_create_file(profile.vault_path, rel_path, content, reason="obsidian-moc: new MOC")
    except p.PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    record = p.apply_patch(profile.vault_path, patch)
    print(json.dumps(record.to_dict(), ensure_ascii=False, indent=2, default=str))
    if record.status == "applied":
        print(f"\nWritten: {rel_path}\nindex_dirty: obsidian-index-sync (skill 18) is not built yet.",
              file=sys.stderr)
    return 0 if record.status == "applied" else 1


def _apply_or_preview(vault_path, patches: List[p.Patch], apply: bool) -> int:
    if not apply:
        for pt in patches:
            print(f"[dry run] {pt.op} on {pt.path}:")
            print(pt.preview_diff or "(no diff - new content)")
            print()
        print("(pass --apply to write both sides)")
        return 0
    ok = True
    for pt in patches:
        rec = p.apply_patch(vault_path, pt)
        print(json.dumps(rec.to_dict(), ensure_ascii=False, indent=2, default=str))
        ok = ok and rec.status in ("applied", "unchanged")
    if ok:
        print("\nindex_dirty: obsidian-index-sync (skill 18) is not built yet.", file=sys.stderr)
    return 0 if ok else 1


def cmd_add_article(args, profile) -> int:
    vault = profile.vault_path
    if not (Path(vault) / args.moc).is_file():
        print(f"error: MOC not found: {args.moc}", file=sys.stderr)
        return 2
    if not (Path(vault) / args.article).is_file():
        print(f"error: article not found: {args.article}", file=sys.stderr)
        return 2
    link = f"[[{args.article[:-3]}]]"
    bullet = f"- {link} — {args.annotation}" if args.annotation else f"- {link}"
    try:
        moc_patch = _propose_list_addition(vault, args.moc, "Статьи", bullet,
                                            reason="obsidian-moc: add-article", sources=[args.article])
        article_patch = p.propose_yaml_merge(vault, args.article, {"moc": [f"[[{args.moc[:-3]}]]"]},
                                              reason="obsidian-moc: reciprocal moc field", sources=[args.moc])
    except p.PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return _apply_or_preview(vault, [moc_patch, article_patch], args.apply)


def cmd_add_child(args, profile) -> int:
    vault = profile.vault_path
    if not (Path(vault) / args.parent_moc).is_file():
        print(f"error: parent MOC not found: {args.parent_moc}", file=sys.stderr)
        return 2
    if not (Path(vault) / args.child_moc).is_file():
        print(f"error: child MOC not found: {args.child_moc}", file=sys.stderr)
        return 2
    if would_create_cycle(profile, args.child_moc, args.parent_moc):
        print(json.dumps({"error": "would_create_cycle", "child_moc": args.child_moc,
                          "parent_moc": args.parent_moc}, ensure_ascii=False, indent=2, default=str),
              file=sys.stderr)
        return 2
    link = f"[[{args.child_moc[:-3]}]]"
    bullet = f"- {link} — {args.annotation}" if args.annotation else f"- {link}"
    try:
        parent_patch = _propose_list_addition(vault, args.parent_moc, "Дочерние MOC", bullet,
                                               reason="obsidian-moc: add-child", sources=[args.child_moc])
        child_patch = p.propose_yaml_merge(vault, args.child_moc, {"parent_mocs": [f"[[{args.parent_moc[:-3]}]]"]},
                                            reason="obsidian-moc: set parent_mocs", sources=[args.parent_moc])
    except p.PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return _apply_or_preview(vault, [parent_patch, child_patch], args.apply)


def main() -> int:
    # --profile/--format are defined on each subparser (via parents=), not
    # the top level - see workflow.py's main() for why ("script.py
    # subcommand --profile X" must work, not only "script.py --profile X
    # subcommand").
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="profile file path or registered vault id")
    common.add_argument("--format", default="md", choices=["md", "json"])

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check-name", help="REQ-FND-0001 uniqueness check for MOC_<title>.md", parents=[common])
    p_check.add_argument("--title", required=True, help="title WITHOUT the MOC_ prefix")
    p_check.add_argument("--folder")
    p_check.add_argument("--batch-titles")

    p_list = sub.add_parser("list-hierarchy", help="discover every type:moc file and its parent/child tree", parents=[common])

    p_cyc = sub.add_parser("check-cycle", help="would this parent assignment create a cycle?", parents=[common])
    p_cyc.add_argument("--moc", required=True)
    p_cyc.add_argument("--parent", required=True)

    p_new = sub.add_parser("new", help="assemble and (optionally) write a new MOC", parents=[common])
    p_new.add_argument("--title", required=True, help="title WITHOUT the MOC_ prefix")
    p_new.add_argument("--perspective", required=True, help="e.g. theory/architecture/implementation/operations/evaluation/use-cases")
    p_new.add_argument("--perspective-question", required=True)
    p_new.add_argument("--summary", required=True)
    p_new.add_argument("--terms", help="comma list of key terms/synonyms")
    p_new.add_argument("--parent", help="path of the single main parent MOC, if any")
    p_new.add_argument("--tags")
    p_new.add_argument("--folder")
    p_new.add_argument("--batch-titles")
    p_new.add_argument("--apply", action="store_true")

    p_art = sub.add_parser("add-article", help="annotate an article into a MOC, and set the article's own moc: field", parents=[common])
    p_art.add_argument("--moc", required=True)
    p_art.add_argument("--article", required=True)
    p_art.add_argument("--annotation", required=True, help="one line: this article's role in this MOC's perspective")
    p_art.add_argument("--apply", action="store_true")

    p_child = sub.add_parser("add-child", help="annotate a child MOC into a parent, and set the child's parent_mocs", parents=[common])
    p_child.add_argument("--parent-moc", required=True)
    p_child.add_argument("--child-moc", required=True)
    p_child.add_argument("--annotation", required=True)
    p_child.add_argument("--apply", action="store_true")

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "check-name":
        return cmd_check_name(args, profile)
    if args.command == "list-hierarchy":
        return cmd_list_hierarchy(args, profile)
    if args.command == "check-cycle":
        return cmd_check_cycle(args, profile)
    if args.command == "new":
        return cmd_new(args, profile)
    if args.command == "add-article":
        return cmd_add_article(args, profile)
    if args.command == "add-child":
        return cmd_add_child(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
