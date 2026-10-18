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

Look (reference: a hand-made HUB, "HUB RAG 2"): macro zones holding stage
groups; a stage = goal card + two columns of text cards, each card a
`[[note#heading|alias]]` link plus an italic line saying what that note
gives *at this point of the route*; nested subgroups; colour = status
with an auto legend; labelled arrows for branches and loops; control
nodes (actor/system) hanging above or below a zone.

Subcommands
-----------
  check-name  - REQ-FND-0001 uniqueness for BOTH HUB_<title>.md/.canvas.
  new         - write the pair from a spec (stages, controls, edges). Dry run
                by default; --apply to write both files.
  validate    - structure, links inside cards, overlaps, group borders.
  preview     - render a canvas to a standalone SVG for a visual check.
  add-card    - add one card below an existing stage group, moving nothing.
  add-stage   - append a new stage group to the right of the existing layout,
                and its section to the paired .md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
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


def make_resolver(profile: VaultProfile):
    """resolve_note(stem, heading) -> ok | missing | no_heading, for the
    wikilinks inside text cards."""
    index = linkgraph.build_basename_index(profile.vault_path, profile.scope)
    canvases = {PurePosixPath(r).name.casefold() for r in
                linkgraph.iter_vault_files(profile.vault_path, profile.scope, extensions={".canvas"})}

    def resolve(note: str, heading: str = "") -> str:
        # a link target is a note name, not a path: only a trailing ".md" is an
        # extension ("... (ГОСТ 34.602-2020)" must keep its dots)
        name = note.rsplit("/", 1)[-1]
        if name.casefold().endswith(".canvas"):
            return "ok" if name.casefold() in canvases else "missing"
        name = name[:-3] if name.endswith(".md") else name
        paths = index.get(pathutil.normalize_basename(name), [])
        if not paths:
            return "missing"
        if heading:
            body = (Path(profile.vault_path) / paths[0]).read_text(encoding="utf-8", errors="ignore")
            if not re.search(rf"^#+\s+{re.escape(heading)}\s*$", body, re.M):
                return "no_heading"
        return "ok"
    return resolve


def _spec_from_file(path: str) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {"stages": data} if isinstance(data, list) else data


def _all_cards(spec: dict):
    for st in spec.get("stages", []):
        for c in st.get("cards", []):
            yield st["name"], c
        for sub in st.get("subgroups", []):
            for c in sub.get("cards", []):
                yield f"{st['name']} / {sub['name']}", c


def _check_spec(profile: VaultProfile, spec: dict) -> tuple:
    """(errors, warnings) for the input spec, before any layout."""
    errors, warns = [], []
    ids = {}
    for st in spec.get("stages", []):
        sid = st.get("id") or st["name"]
        if sid in ids:
            errors.append(f"duplicate stage id {sid!r}")
        ids[sid] = "stage"
        if not st.get("goal"):
            warns.append(f"stage {st['name']!r} has no goal")
    for where, raw in _all_cards(spec):
        c = cv.normalize_card(raw)
        if c.get("id"):
            if c["id"] in ids:
                errors.append(f"duplicate id {c['id']!r}")
            ids[c["id"]] = "card"
        if c["kind"] in ("note", "embed"):
            if not (Path(profile.vault_path) / c["note"]).is_file():
                errors.append(f"[{where}] card target does not exist: {c['note']}")
            elif c["kind"] == "note" and not c.get("desc"):
                warns.append(f"[{where}] {c['note']}: no desc - say what this note gives at this point of the route")
    for ctl in spec.get("controls", []):
        ids[ctl["id"]] = "control"
        if ctl.get("near") not in ids:
            errors.append(f"control {ctl['id']!r}: unknown stage {ctl.get('near')!r}")
    for e in spec.get("edges", []):
        for end in ("from", "to"):
            if e[end] not in ids and not e[end].startswith("zone:"):
                errors.append(f"edge {e['from']!r}->{e['to']!r}: unknown {end} id {e[end]!r}")
    return errors, warns


def _card_md_line(raw: dict) -> str:
    c = cv.normalize_card(raw)
    if c["kind"] == "text":
        return ""
    stem = PurePosixPath(c["note"]).stem
    target = stem + (f"#{c['heading']}" if c.get("heading") else "")
    alias = c.get("alias") or c.get("label") or c.get("heading") or stem
    line = f"- [[{target}|{alias}]]" if alias != target else f"- [[{target}]]"
    return line + (f" — {c['desc']}" if c.get("desc") else "")


def _stage_md_section(i: int, stage: dict) -> str:
    lines = [f"### {i}. {stage['name']}", ""]
    if stage.get("zone"):
        lines += [f"**Зона:** {stage['zone']}", ""]
    if stage.get("goal"):
        lines += [f"**Цель:** {stage['goal']}", ""]
    if stage.get("materials"):
        lines += ["**Материалы:**"] + [f"- {m}" for m in stage["materials"]] + [""]
    if stage.get("action"):
        lines += [f"**Действие:** {stage['action']}", ""]
    if stage.get("expected_result"):
        lines += [f"**Ожидаемый результат:** {stage['expected_result']}", ""]
    cards = [l for l in (_card_md_line(c) for c in stage.get("cards", [])) if l]
    lines += cards + ([""] if cards else [])
    for sub in stage.get("subgroups", []):
        sub_cards = [l for l in (_card_md_line(c) for c in sub.get("cards", [])) if l]
        lines += [f"**{sub['name']}**"] + sub_cards + [""]
    return "\n".join(lines).rstrip() + "\n"


def _branches_md(spec: dict) -> str:
    names = {}
    for st in spec.get("stages", []):
        names[st.get("id") or st["name"]] = st["name"]
    for _, c in _all_cards(spec):
        c = cv.normalize_card(c)
        if c.get("id"):
            names[c["id"]] = c.get("alias") or c.get("heading") or PurePosixPath(c.get("note", c["id"])).stem
    for ctl in spec.get("controls", []):
        names[ctl["id"]] = ctl["text"].split("\n")[0]
    rows = []
    sts = spec.get("stages", [])
    if spec.get("spine", True):
        for a, b in zip(sts, sts[1:]):
            rows.append(f"- {a['name']} → {b['name']}" + (f": {a['next_label']}" if a.get("next_label") else ""))
    for e in spec.get("edges", []):
        rows.append(f"- {names.get(e['from'], e['from'])} → {names.get(e['to'], e['to'])}"
                    + (f": {e['label']}" if e.get("label") else ""))
    return "\n".join(rows)


def _legend_md(spec: dict) -> str:
    used = set()
    for st in spec.get("stages", []):
        if st.get("color"):
            used.add(st["color"])
        for sub in st.get("subgroups", []):
            if sub.get("color"):
                used.add(sub["color"])
    for _, raw in _all_cards(spec):
        col = cv.normalize_card(raw).get("color")
        if col:
            used.add(col)
    texts = {**cv.DEFAULT_LEGEND, **spec.get("legend", {})}
    return "\n".join(f"- цвет {c}: {texts[c]}" for c in sorted(used) if c in texts)


def cmd_new(args, profile) -> int:
    folder = args.folder or profile.managed_folders.hub
    name_check = check_name(profile, args.title, folder)
    if not name_check["unique"]:
        print("error: name is not unique for the .md/.canvas pair - run check-name and apply a project code first",
              file=sys.stderr)
        print(json.dumps(name_check, ensure_ascii=False, indent=2, default=str), file=sys.stderr)
        return 2

    spec = _spec_from_file(args.spec_file)
    stages = spec.get("stages", [])
    if not stages:
        print("error: spec has no stages", file=sys.stderr)
        return 2
    errors, warns = _check_spec(profile, spec)
    for w in warns:
        print(f"warning: {w}", file=sys.stderr)
    if errors:
        print("error: invalid spec:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 2

    nodes, edges = cv.build_hub_layout(spec)
    issues = cv.validate_canvas(profile.vault_path, nodes, edges, resolve_note=make_resolver(profile))
    for i in issues:
        if i.severity != "error":
            print(f"warning: {i.message}", file=sys.stderr)
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
    branches_body = args.branches or _branches_md(spec) or "_нет_"
    legend = _legend_md(spec)
    md_body = (
        f"\n# HUB — {args.title}\n\n"
        f"## Summary\n\n{args.summary}\n\n"
        f"## Основные термины\n\n{terms_body}\n\n"
        f"## Этапы\n\n{stages_body}\n\n"
        f"## Ветвления и альтернативы\n\n{branches_body}\n\n"
        + (f"## Легенда цветов\n\n{legend}\n\n" if legend else "")
        +         f"## Связанный Canvas\n\n![[{PurePosixPath(name_check['canvas_path']).name}]]\n"
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
        print(f"\nindex_dirty: run obsidian-index-sync on {name_check['md_path']} and "
              f"{name_check['canvas_path']} - neither half is in the search index yet.", file=sys.stderr)
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
    issues = cv.validate_canvas(profile.vault_path, parsed.nodes, parsed.edges, resolve_note=make_resolver(profile))
    result = {
        "path": args.path, "nodes": len(parsed.nodes), "edges": len(parsed.edges),
        "issues": [{"severity": i.severity, "message": i.message} for i in issues],
        "ok": not any(i.severity == "error" for i in issues),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


def cmd_preview(args, profile) -> int:
    full = Path(profile.vault_path) / args.path
    parsed = cv.parse_canvas(full.read_text(encoding="utf-8")) if full.is_file() else None
    if parsed is None or parsed.error:
        print(f"error: cannot read canvas {args.path}: {parsed.error if parsed else 'not found'}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.write_text(cv.render_svg(parsed.nodes, parsed.edges), encoding="utf-8")
    print(json.dumps({"svg": str(out), "nodes": len(parsed.nodes), "edges": len(parsed.edges)}, ensure_ascii=False))
    return 0


def cmd_add_card(args, profile) -> int:
    full = Path(profile.vault_path) / args.canvas
    if not full.is_file():
        print(f"error: canvas not found: {args.canvas}", file=sys.stderr)
        return 2
    note = args.note or args.file
    if note and not (Path(profile.vault_path) / note).is_file():
        print(f"error: note does not exist: {note}", file=sys.stderr)
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
    card = {"note": note, "heading": (args.heading or (args.subpath or "").lstrip("#")) or None,
            "alias": args.alias, "desc": args.desc, "status": args.status, "text": args.text}
    if not note:
        card.pop("note")
    new_node = cv.add_card_near_group(parsed.nodes, group, card)

    if not args.apply:
        print(f"[dry run] would add to {args.canvas}: {json.dumps(new_node, ensure_ascii=False)}")
        return 0
    new_nodes = parsed.nodes + [new_node]
    rec = cv.write_canvas(profile.vault_path, args.canvas, new_nodes, parsed.edges,
                           based_on_hash=cv.canvas_hash(raw))
    print(json.dumps({"path": args.canvas, **rec.__dict__}, ensure_ascii=False, indent=2, default=str))
    if rec.status == "applied":
        print(f"\nindex_dirty: run obsidian-index-sync on {args.canvas}.", file=sys.stderr)
    return 0 if rec.status == "applied" else 1


def cmd_add_stage(args, profile) -> int:
    canvas_full = Path(profile.vault_path) / args.canvas
    if not canvas_full.is_file():
        print(f"error: canvas not found: {args.canvas}", file=sys.stderr)
        return 2
    stage = json.loads(Path(args.stage_file).read_text(encoding="utf-8"))
    errors, warns = _check_spec(profile, {"stages": [stage]})
    for w in warns:
        print(f"warning: {w}", file=sys.stderr)
    if errors:
        print("error: invalid stage:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
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

    # The new stage hangs to the right of everything and is wired in from
    # the previous stage: --after, else the last '### N. name' of the paired .md.
    after_name = args.after
    if not after_name:
        md_text = (Path(profile.vault_path) / args.md).read_text(encoding="utf-8")
        found = re.findall(r"^###\s+\d+\.\s+(.+?)\s*$", md_text, re.M)
        after_name = found[-1] if found else None
    after = cv.find_group_by_label(parsed.nodes, after_name) if after_name else None
    max_right = max((n["x"] + n["width"] for n in parsed.nodes), default=-cv.STAGE_GAP)
    new_nodes, new_edges = cv.build_hub_layout({"stages": [{**stage, "zone": None}], "no_legend": True})
    new_group = new_nodes[0]
    cv._shift(new_nodes, max_right + cv.STAGE_GAP, after["y"] if after else 0)
    if after is not None:
        fs, ts = cv._auto_sides(after, new_group)
        new_edges.append({"id": cv.new_id(), "fromNode": after["id"], "fromSide": fs,
                          "toNode": new_group["id"], "toSide": ts})
    elif after_name:
        print(f"warning: no group labelled {after_name!r}; the new stage is not wired to anything",
              file=sys.stderr)

    combined_nodes = parsed.nodes + new_nodes
    combined_edges = parsed.edges + new_edges
    issues = cv.validate_canvas(profile.vault_path, combined_nodes, combined_edges, resolve_note=make_resolver(profile))
    errors = [i for i in issues if i.severity == "error"]
    if errors:
        print("error: resulting canvas would fail validation:", file=sys.stderr)
        for i in errors:
            print(f"  - {i.message}", file=sys.stderr)
        return 2

    stage_number = 1 + len(re.findall(r"^###\s+\d+\.", (Path(profile.vault_path) / args.md).read_text(encoding="utf-8"), re.M))
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
        print(f"\nindex_dirty: run obsidian-index-sync on {args.canvas} and {args.md}.", file=sys.stderr)
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
    p_new.add_argument("--spec-file", "--stages-file", dest="spec_file", required=True,
                        help="JSON spec {stages, controls?, edges?, spine?, legend?} or a bare stage list; "
                             "see SKILL.md for the card shape")
    p_new.add_argument("--folder")
    p_new.add_argument("--apply", action="store_true")

    p_val = sub.add_parser("validate", help="JSON Canvas structural checks", parents=[common])
    p_val.add_argument("--path", required=True)

    p_card = sub.add_parser("add-card", help="add one card next to an existing stage group", parents=[common])
    p_card.add_argument("--canvas", required=True)
    p_card.add_argument("--stage", required=True, help="the target group's label")
    p_card.add_argument("--note", help="vault-relative path of the note to link")
    p_card.add_argument("--file", help="alias of --note (older name)")
    p_card.add_argument("--heading", help="anchor the link to a section of the note")
    p_card.add_argument("--subpath", help="older form of --heading, '#Heading'")
    p_card.add_argument("--alias", help="link text on the card")
    p_card.add_argument("--desc", help="what this note gives at this point of the route (italic line)")
    p_card.add_argument("--status", choices=sorted(cv.STATUS_COLORS), help="colour the card by status")
    p_card.add_argument("--text", help="text for a plain text card (omit --note)")
    p_card.add_argument("--apply", action="store_true")

    p_stage = sub.add_parser("add-stage", help="append a new stage to the right of the existing layout", parents=[common])
    p_stage.add_argument("--canvas", required=True)
    p_stage.add_argument("--md", required=True, help="the paired HUB_<title>.md to also update")
    p_stage.add_argument("--after", help="stage the new one follows (default: the last stage in the .md)")
    p_stage.add_argument("--stage-file", required=True, help="JSON: one stage object, same shape as in --stages-file")
    p_stage.add_argument("--apply", action="store_true")

    p_prev = sub.add_parser("preview", help="render a canvas to a standalone SVG", parents=[common])
    p_prev.add_argument("--path", required=True, help="vault-relative .canvas")
    p_prev.add_argument("--out", required=True, help="output .svg path")

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
    if args.command == "preview":
        return cmd_preview(args, profile)
    if args.command == "add-card":
        if not (args.note or args.file or args.text):
            print("error: give --note (link card) or --text (text card)", file=sys.stderr)
            return 2
        return cmd_add_card(args, profile)
    if args.command == "add-stage":
        return cmd_add_stage(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
