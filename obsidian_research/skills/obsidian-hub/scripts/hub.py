#!/usr/bin/env python3
"""obsidian-hub: create and grow a HUB - the mandatory `.md` + `.canvas`
pair that shows a work/learning route across MOCs and articles.

Implements spec passport 09-obsidian-hub.md (US-008), ADR-0003 (paired
Markdown + Canvas, native JSON Canvas), and REQ-FND-0001 (both halves of
the pair get the same uniqueness check and the same project-code prefix
on collision). The Markdown side is written through
`lib/obsidian_common/patch.py`, exactly like every other skill's writes;
the Canvas side is written through `lib/obsidian_common/canvas.py`, which
never touches an existing node/edge's id/x/y/width/height - only ever
appends (H9: preserve manual layout, add new material next to a stage).

Subcommands
-----------
  check-name  - REQ-FND-0001 uniqueness for BOTH HUB_<title>.md/.canvas.
  new         - write the pair from a stages description. Dry run by
                default; --apply to write both files.
  validate    - JSON Canvas structural checks (§3.9 "Проверки").
  add-card    - add one file/text card positioned next to an existing
                stage group, without moving anything already there.
  add-stage   - append a new stage group (+ its cards) to the right of
                the existing layout, and its section to the paired .md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path, PurePosixPath
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import canvas as cv  # noqa: E402
from obsidian_common import linkgraph, markdown as md, pathutil  # noqa: E402
from obsidian_common import patch as p  # noqa: E402
from obsidian_common.frontmatter_ops import serialize_frontmatter  # noqa: E402
from obsidian_common.profile import ProfileError, VaultProfile, resolve_profile  # noqa: E402


def check_name(profile: VaultProfile, title: str, folder: str) -> dict:
    prefix = profile.naming.hub_prefix
    md_name, canvas_name = f"{prefix}{title}.md", f"{prefix}{title}.canvas"
    md_rel = f"{folder.rstrip('/')}/{md_name}" if folder else md_name
    canvas_rel = f"{folder.rstrip('/')}/{canvas_name}" if folder else canvas_name
    index = linkgraph.build_basename_index(profile.vault_path, profile.scope)
    md_collisions = index.get(pathutil.normalize_basename(f"{prefix}{title}"), [])
    return {
        "title": title, "md_path": md_rel, "canvas_path": canvas_rel,
        "md_exists": (Path(profile.vault_path) / md_rel).is_file(),
        "canvas_exists": (Path(profile.vault_path) / canvas_rel).is_file(),
        "vault_wide_basename_collisions": md_collisions,
        "unique": not md_collisions and not (Path(profile.vault_path) / md_rel).is_file()
                  and not (Path(profile.vault_path) / canvas_rel).is_file(),
        "project_codes_available": profile.naming.project_codes,
    }


def cmd_check_name(args, profile) -> int:
    result = check_name(profile, args.title, args.folder or profile.managed_folders.hub)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["unique"] else 1


def _stage_md_section(i: int, stage: dict) -> str:
    lines = [f"### {i}. {stage['name']}", ""]
    if stage.get("goal"):
        lines += [f"**Цель:** {stage['goal']}", ""]
    if stage.get("materials"):
        lines += ["**Материалы:**"] + [f"- {m}" for m in stage["materials"]] + [""]
    if stage.get("action"):
        lines += [f"**Действие:** {stage['action']}", ""]
    if stage.get("expected_result"):
        lines += [f"**Ожидаемый результат:** {stage['expected_result']}", ""]
    for card in stage.get("cards", []):
        if card.get("kind", "file") == "file":
            label = card.get("label") or PurePosixPath(card["file"]).stem
            lines.append(f"- [[{card['file'][:-3]}{card.get('subpath','')}|{label}]]")
    return "\n".join(lines).rstrip() + "\n"


def cmd_new(args, profile) -> int:
    folder = args.folder or profile.managed_folders.hub
    name_check = check_name(profile, args.title, folder)
    if not name_check["unique"]:
        print("error: name is not unique for the .md/.canvas pair - run check-name and apply a project code first",
              file=sys.stderr)
        print(json.dumps(name_check, ensure_ascii=False, indent=2, default=str), file=sys.stderr)
        return 2

    stages = json.loads(Path(args.stages_file).read_text(encoding="utf-8"))
    for stage in stages:
        for card in stage.get("cards", []):
            if card.get("kind", "file") == "file" and not (Path(profile.vault_path) / card["file"]).is_file():
                print(f"error: card target does not exist: {card['file']}", file=sys.stderr)
                return 2

    nodes, edges = cv.build_stage_layout(stages)
    issues = cv.validate_canvas(profile.vault_path, nodes, edges)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        print("error: generated canvas failed validation:", file=sys.stderr)
        for i in errors:
            print(f"  - {i.message}", file=sys.stderr)
        return 2

    today = dt.date.today().isoformat()
    terms = [t.strip() for t in (args.terms or "").split(",") if t.strip()]
    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    meta = {
        "type": "hub", "status": "draft", "purpose": args.purpose, "summary": args.summary,
        "terms": terms, "route_type": args.route_type, "canvas": f"[[{name_check['canvas_path']}]]",
        "tags": tags, "created": today, "updated": today,
    }
    terms_body = "\n".join(f"- {t}" for t in terms) if terms else "_нет_"
    stages_body = "\n\n".join(_stage_md_section(i, s) for i, s in enumerate(stages, start=1))
    branches_body = args.branches or "_нет_"
    md_body = (
        f"\n# HUB — {args.title}\n\n"
        f"## Summary\n\n{args.summary}\n\n"
        f"## Основные термины\n\n{terms_body}\n\n"
        f"## Этапы\n\n{stages_body}\n\n"
        f"## Ветвления и альтернативы\n\n{branches_body}\n\n"
        f"## Связанный Canvas\n\n![[{PurePosixPath(name_check['canvas_path']).name}]]\n"
    )
    md_content = serialize_frontmatter(meta) + md_body
    canvas_content = cv.serialize_canvas(nodes, edges)

    if not args.apply:
        print(f"[dry run] would create: {name_check['md_path']}\n")
        print(md_content)
        print(f"\n[dry run] would create: {name_check['canvas_path']} "
              f"({len(nodes)} nodes, {len(edges)} edges)")
        return 0

    try:
        md_patch = p.propose_create_file(profile.vault_path, name_check["md_path"], md_content,
                                          reason="obsidian-hub: new HUB")
    except p.PatchError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    md_rec = p.apply_patch(profile.vault_path, md_patch)
    print(json.dumps(md_rec.to_dict(), ensure_ascii=False, indent=2, default=str))
    if md_rec.status != "applied":
        return 1
    canvas_rec = cv.write_canvas(profile.vault_path, name_check["canvas_path"], nodes, edges, based_on_hash=None)
    print(json.dumps({"path": name_check["canvas_path"], **canvas_rec.__dict__}, ensure_ascii=False, indent=2, default=str))
    if canvas_rec.status == "applied":
        print("\nindex_dirty: obsidian-index-sync (skill 18) is not built yet - "
              "neither half of this HUB is indexed.", file=sys.stderr)
    return 0 if canvas_rec.status == "applied" else 1


def cmd_validate(args, profile) -> int:
    full = Path(profile.vault_path) / args.path
    if not full.is_file():
        print(json.dumps({"path": args.path, "error": "not_found"}, ensure_ascii=False, indent=2, default=str))
        return 1
    parsed = cv.parse_canvas(full.read_text(encoding="utf-8"))
    if parsed.error:
        print(json.dumps({"path": args.path, "error": parsed.error}, ensure_ascii=False, indent=2, default=str))
        return 1
    issues = cv.validate_canvas(profile.vault_path, parsed.nodes, parsed.edges)
    result = {
        "path": args.path, "nodes": len(parsed.nodes), "edges": len(parsed.edges),
        "issues": [{"severity": i.severity, "message": i.message} for i in issues],
        "ok": not any(i.severity == "error" for i in issues),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


def cmd_add_card(args, profile) -> int:
    full = Path(profile.vault_path) / args.canvas
    if not full.is_file():
        print(f"error: canvas not found: {args.canvas}", file=sys.stderr)
        return 2
    if args.file and not (Path(profile.vault_path) / args.file).is_file():
        print(f"error: file target does not exist: {args.file}", file=sys.stderr)
        return 2
    raw = full.read_text(encoding="utf-8")
    parsed = cv.parse_canvas(raw)
    if parsed.error:
        print(f"error: {parsed.error}", file=sys.stderr)
        return 2
    group = cv.find_group_by_label(parsed.nodes, args.stage)
    if group is None:
        labels = sorted({n.get("label") for n in parsed.nodes if n.get("type") == "group"})
        print(f"error: no group labeled {args.stage!r}. Existing stages: {labels}", file=sys.stderr)
        return 2
    card = {"kind": "file" if args.file else "text",
            "file": args.file, "subpath": args.subpath, "text": args.text}
    new_node = cv.add_card_near_group(parsed.nodes, group, card)

    if not args.apply:
        print(f"[dry run] would add to {args.canvas}: {json.dumps(new_node, ensure_ascii=False)}")
        return 0
    new_nodes = parsed.nodes + [new_node]
    rec = cv.write_canvas(profile.vault_path, args.canvas, new_nodes, parsed.edges,
                           based_on_hash=cv.canvas_hash(raw))
    print(json.dumps({"path": args.canvas, **rec.__dict__}, ensure_ascii=False, indent=2, default=str))
    if rec.status == "applied":
        print("\nindex_dirty: obsidian-index-sync (skill 18) is not built yet.", file=sys.stderr)
    return 0 if rec.status == "applied" else 1


def cmd_add_stage(args, profile) -> int:
    canvas_full = Path(profile.vault_path) / args.canvas
    if not canvas_full.is_file():
        print(f"error: canvas not found: {args.canvas}", file=sys.stderr)
        return 2
    stage = json.loads(Path(args.stage_file).read_text(encoding="utf-8"))
    for card in stage.get("cards", []):
        if card.get("kind", "file") == "file" and not (Path(profile.vault_path) / card["file"]).is_file():
            print(f"error: card target does not exist: {card['file']}", file=sys.stderr)
            return 2

    raw = canvas_full.read_text(encoding="utf-8")
    parsed = cv.parse_canvas(raw)
    if parsed.error:
        print(f"error: {parsed.error}", file=sys.stderr)
        return 2
    if cv.find_group_by_label(parsed.nodes, stage["name"]) is not None:
        print(json.dumps({"status": "unchanged", "detail": f"a stage group named {stage['name']!r} already exists"},
                          ensure_ascii=False, indent=2, default=str))
        return 0
    max_right = max((n["x"] + n["width"] for n in parsed.nodes if n.get("type") == "group"), default=-cv.STAGE_GAP)
    new_nodes, new_edges = cv.build_stage_layout([stage])
    shift = max_right + cv.STAGE_GAP
    for n in new_nodes:
        n["x"] += shift
    new_group_id = new_nodes[0]["id"]
    last_existing_group = max(
        (n for n in parsed.nodes if n.get("type") == "group"), key=lambda n: n["x"], default=None
    )
    if last_existing_group is not None:
        new_edges.append({"id": cv.new_id(), "fromNode": last_existing_group["id"], "fromSide": "right",
                           "toNode": new_group_id, "toSide": "left", "label": "next"})

    combined_nodes = parsed.nodes + new_nodes
    combined_edges = parsed.edges + new_edges
    issues = cv.validate_canvas(profile.vault_path, combined_nodes, combined_edges)
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        print("error: resulting canvas would fail validation:", file=sys.stderr)
        for i in errors:
            print(f"  - {i.message}", file=sys.stderr)
        return 2

    stage_number = 1 + sum(
        1 for n in parsed.nodes if n.get("type") == "group"
    )
    md_addition = _stage_md_section(stage_number, stage)

    if not args.apply:
        print(f"[dry run] would add stage group ({len(new_nodes)} nodes) to {args.canvas}")
        print(f"[dry run] would append to {args.md} under '## Этапы':\n{md_addition}")
        return 0

    canvas_rec = cv.write_canvas(profile.vault_path, args.canvas, combined_nodes, combined_edges,
                                  based_on_hash=cv.canvas_hash(raw))
    print(json.dumps({"path": args.canvas, **canvas_rec.__dict__}, ensure_ascii=False, indent=2, default=str))
    if canvas_rec.status != "applied":
        return 1
    try:
        # append_subsection, not append_section: '## Этапы' has no leaf
        # text of its own, its content IS its '### N. Stage' children, so
        # this must land after the last existing one, not before all of
        # them (see propose_append_subsection's docstring).
        md_patch = p.propose_append_subsection(profile.vault_path, args.md, "Этапы", md_addition,
                                                reason="obsidian-hub: add-stage")
    except p.PatchError as exc:
        print(f"error on .md side (canvas already written - fix manually or re-run "
              f"obsidian-revise on {args.md}): {exc}", file=sys.stderr)
        return 1
    md_rec = p.apply_patch(profile.vault_path, md_patch)
    print(json.dumps(md_rec.to_dict(), ensure_ascii=False, indent=2, default=str))
    if md_rec.status == "applied":
        print("\nindex_dirty: obsidian-index-sync (skill 18) is not built yet.", file=sys.stderr)
    return 0 if md_rec.status in ("applied", "unchanged") else 1


def main() -> int:
    # --profile is defined on each subparser (via parents=), not the top
    # level - see workflow.py's main() for why ("script.py subcommand
    # --profile X" must work, not only "script.py --profile X subcommand").
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="profile file path or registered vault id")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check-name", help="REQ-FND-0001 uniqueness for the .md/.canvas pair", parents=[common])
    p_check.add_argument("--title", required=True, help="title WITHOUT the HUB_ prefix")
    p_check.add_argument("--folder")

    p_new = sub.add_parser("new", help="write a new HUB_<title>.md + .canvas pair", parents=[common])
    p_new.add_argument("--title", required=True)
    p_new.add_argument("--purpose", required=True)
    p_new.add_argument("--summary", required=True)
    p_new.add_argument("--route-type", default="workflow", choices=["workflow", "learning"])
    p_new.add_argument("--terms")
    p_new.add_argument("--tags")
    p_new.add_argument("--branches", help="text for '## Ветвления и альтернативы'")
    p_new.add_argument("--stages-file", required=True,
                        help="JSON: [{name, goal, materials?, action?, expected_result?, "
                             "cards:[{kind:file|text, file?, subpath?, text?, label?}]}]")
    p_new.add_argument("--folder")
    p_new.add_argument("--apply", action="store_true")

    p_val = sub.add_parser("validate", help="JSON Canvas structural checks", parents=[common])
    p_val.add_argument("--path", required=True)

    p_card = sub.add_parser("add-card", help="add one card next to an existing stage group", parents=[common])
    p_card.add_argument("--canvas", required=True)
    p_card.add_argument("--stage", required=True, help="the target group's label")
    p_card.add_argument("--file", help="vault-relative path for a file card")
    p_card.add_argument("--subpath", help="e.g. '#Heading' to anchor the file card to a section")
    p_card.add_argument("--text", help="text for a text card (omit --file to make a text card)")
    p_card.add_argument("--apply", action="store_true")

    p_stage = sub.add_parser("add-stage", help="append a new stage to the right of the existing layout", parents=[common])
    p_stage.add_argument("--canvas", required=True)
    p_stage.add_argument("--md", required=True, help="the paired HUB_<title>.md to also update")
    p_stage.add_argument("--stage-file", required=True, help="JSON: one stage object, same shape as in --stages-file")
    p_stage.add_argument("--apply", action="store_true")

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "check-name":
        return cmd_check_name(args, profile)
    if args.command == "new":
        return cmd_new(args, profile)
    if args.command == "validate":
        return cmd_validate(args, profile)
    if args.command == "add-card":
        if not args.file and not args.text:
            print("error: give --file (file card) or --text (text card)", file=sys.stderr)
            return 2
        return cmd_add_card(args, profile)
    if args.command == "add-stage":
        return cmd_add_stage(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
