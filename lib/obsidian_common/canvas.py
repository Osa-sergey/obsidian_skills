"""JSON Canvas 1.0 read/write/layout, matching Obsidian's own on-disk format.

Spec: https://jsoncanvas.org/spec/1.0/ - node types `text`/`file`/`link`/
`group`; edge fields `fromNode`/`fromSide`/`toNode`/`toSide`/`label`.
Backs obsidian-hub (§3.9): the visual half of the mandatory `.md` + `.canvas`
pair (ADR-0003). Canvas is JSON, not Markdown - none of this package's
heading/frontmatter machinery applies here, this module is self-contained.

`serialize_canvas` matches Obsidian's own compact, tab-indented output
byte for byte (verified 2026-09-29 against a real `.canvas` file already
in this vault: top-level object indented one tab, each node/edge object
compact JSON on its own line indented two tabs) specifically so a
machine-touched canvas keeps looking hand-edited in a diff, not
machine-dumped.
"""
from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from .write import atomic_write

VALID_NODE_TYPES = {"text", "file", "link", "group"}

# Layout constants, taken from the reference HUB (HUB RAG 2): a stage
# group is two card columns wide, cards are padded 26 inside a group and
# 18 apart. Not configurable per call on purpose - consistent geometry
# across generated HUBs beats per-call tuning, and an existing HUB's own
# manual layout is never touched by these (see add_card_near_group / H9).
COL_W = 310                      # one card column
CARD_GAP = 18
PAD = 26                         # group padding
GROUP_W = 2 * COL_W + CARD_GAP + 2 * PAD   # 690
INNER_W = GROUP_W - 2 * PAD                # 638, a "wide" card
STAGE_GAP = 160                  # between stage groups in a row
SUB_PAD = 18                     # padding inside a nested subgroup
LABEL_SPACE = 40                 # Obsidian draws a group's label above its box
ZONE_PAD_X = 40
ZONE_PAD_TOP = 90
ZONE_PAD_BOTTOM = 40
ZONE_GAP = 180
CONTROL_W = 240
MAX_COLS = 4                     # stages per row before wrapping

# Colour = status, as in the reference (Obsidian presets "1".."6").
STATUS_COLORS = {"warn": "1", "tip": "3", "new": "4", "stub": "5", "cross": "6"}
DEFAULT_LEGEND = {
    "1": "предупреждение / риск",
    "3": "приём, практика, улучшение",
    "4": "новый материал",
    "5": "заглушка — материала пока нет",
    "6": "сквозная тема",
}


def new_id() -> str:
    return uuid.uuid4().hex[:16]  # matches the length Obsidian's own IDs use


@dataclass
class ParsedCanvas:
    nodes: List[dict]
    edges: List[dict]
    error: Optional[str] = None


def parse_canvas(text: str) -> ParsedCanvas:
    if not text.strip():
        return ParsedCanvas([], [])
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return ParsedCanvas([], [], error=f"invalid JSON: {exc}")
    if not isinstance(data, dict):
        return ParsedCanvas([], [], error="canvas root must be a JSON object")
    nodes, edges = data.get("nodes", []), data.get("edges", [])
    if not isinstance(nodes, list) or not isinstance(edges, list):
        return ParsedCanvas([], [], error="'nodes' and 'edges' must be arrays")
    return ParsedCanvas(nodes, edges)


def serialize_canvas(nodes: List[dict], edges: List[dict]) -> str:
    def compact(obj: dict) -> str:
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))

    def array_block(items: List[dict]) -> str:
        if not items:
            return "[]"
        body = ",\n".join(f"\t\t{compact(it)}" for it in items)
        return "[\n" + body + "\n\t]"

    return (
        "{\n"
        f"\t\"nodes\":{array_block(nodes)},\n"
        f"\t\"edges\":{array_block(edges)}\n"
        "}"
    )


@dataclass
class CanvasIssue:
    severity: str  # error | warning
    message: str


def validate_canvas(vault_path: Path, nodes: List[dict], edges: List[dict],
                    resolve_note=None) -> List[CanvasIssue]:
    """§3.9 "Проверки": valid structure, unique IDs, every edge endpoint
    and every file-card target actually exists, no degenerate sizes, no
    two nodes sharing identical geometry (a likely copy/paste mistake)."""
    issues: List[CanvasIssue] = []
    ids = [n.get("id") for n in nodes]
    dupe_ids = {i for i in ids if ids.count(i) > 1 and i is not None}
    if dupe_ids:
        issues.append(CanvasIssue("error", f"duplicate node id(s): {sorted(dupe_ids)}"))
    id_set = set(ids)

    edge_ids = [e.get("id") for e in edges]
    dupe_edge_ids = {i for i in edge_ids if edge_ids.count(i) > 1 and i is not None}
    if dupe_edge_ids:
        issues.append(CanvasIssue("error", f"duplicate edge id(s): {sorted(dupe_edge_ids)}"))

    geometry_seen: Dict[tuple, str] = {}
    for n in nodes:
        nid = n.get("id", "?")
        ntype = n.get("type")
        if ntype not in VALID_NODE_TYPES:
            issues.append(CanvasIssue("error", f"node {nid}: unknown type {ntype!r}"))
        if ntype == "file":
            target = n.get("file")
            if not target:
                issues.append(CanvasIssue("error", f"node {nid}: file node missing 'file'"))
            elif not (Path(vault_path) / target).is_file():
                issues.append(CanvasIssue("error", f"node {nid}: file target does not exist: {target}"))
        for dim in ("width", "height"):
            if n.get(dim, 1) <= 0:
                issues.append(CanvasIssue("warning", f"node {nid}: non-positive {dim}"))
        geom = (n.get("x"), n.get("y"), n.get("width"), n.get("height"))
        if geom in geometry_seen:
            issues.append(CanvasIssue("warning", f"nodes {geometry_seen[geom]} and {nid} share identical geometry"))
        else:
            geometry_seen[geom] = nid

    for e in edges:
        eid = e.get("id", "?")
        if e.get("fromNode") not in id_set:
            issues.append(CanvasIssue("error", f"edge {eid}: fromNode {e.get('fromNode')!r} does not exist"))
        if e.get("toNode") not in id_set:
            issues.append(CanvasIssue("error", f"edge {eid}: toNode {e.get('toNode')!r} does not exist"))
    issues += _check_geometry(nodes)
    if resolve_note is not None:
        issues += _check_text_links(nodes, resolve_note)
    return issues


def _inter(a: dict, b: dict) -> bool:
    return (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["width"]
            and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"])


def _inside(inner: dict, outer: dict) -> bool:
    return (inner["x"] >= outer["x"] and inner["y"] >= outer["y"]
            and inner["x"] + inner["width"] <= outer["x"] + outer["width"]
            and inner["y"] + inner["height"] <= outer["y"] + outer["height"])


def _check_geometry(nodes: List[dict]) -> List[CanvasIssue]:
    """No unintended overlaps: two content nodes must not intersect, and
    a node must not straddle a group's border (inside or fully outside)."""
    out: List[CanvasIssue] = []
    boxed = [n for n in nodes if all(isinstance(n.get(k), (int, float)) for k in ("x", "y", "width", "height"))]
    groups = [n for n in boxed if n.get("type") == "group"]
    others = [n for n in boxed if n.get("type") != "group"]

    def name(n):
        return n.get("label") or (n.get("text") or n.get("file") or "")[:30].replace("\n", " ") or n["id"]

    for i, a in enumerate(others):
        for b in others[i + 1:]:
            if _inter(a, b):
                out.append(CanvasIssue("warning", f"cards overlap: {name(a)!r} and {name(b)!r}"))
    for g in groups:
        for n in boxed:
            if n is g or n.get("type") == "group" and _inside(g, n):
                continue
            if _inter(g, n) and not _inside(n, g):
                out.append(CanvasIssue("warning", f"{name(n)!r} straddles the border of group {name(g)!r}"))
    return out


def _check_text_links(nodes: List[dict], resolve_note) -> List[CanvasIssue]:
    """Every [[wikilink]] in a text card must point at an existing note
    (`resolve_note(target) -> bool`); a `#heading` that is not in the note
    silently opens the top of it, so flag that too."""
    out: List[CanvasIssue] = []
    for n in nodes:
        if n.get("type") != "text":
            continue
        for m in _WIKILINK.finditer(n.get("text", "")):
            target = m.group(1)
            note, _, heading = target.partition("#")
            res = resolve_note(note, heading)
            if res == "missing":
                out.append(CanvasIssue("error", f"text card {n['id']}: link target not found: [[{note}]]"))
            elif res == "no_heading":
                out.append(CanvasIssue("warning", f"text card {n['id']}: heading {heading!r} not found in [[{note}]]"))
    return out


_WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def normalize_card(card: dict) -> dict:
    """One card shape from either input dialect. New: {note, heading?,
    alias?, desc?, status?|color?, wide?, id?} or {text, color?}; legacy
    {kind:"file", file, subpath?, label?} is a note card without a
    description; {kind:"embed", file} is a real Obsidian file node."""
    c = dict(card)
    kind = c.get("kind")
    if kind == "embed":
        c["kind"] = "embed"
    elif c.get("note") or c.get("file"):
        c["kind"] = "note"
        c["note"] = c.get("note") or c["file"]
        if not c.get("heading") and c.get("subpath"):
            c["heading"] = c["subpath"].lstrip("#")
    else:
        c["kind"] = "text"
    if c.get("status") and not c.get("color"):
        c["color"] = STATUS_COLORS.get(c["status"], c["status"])
    return c


def card_text(c: dict) -> str:
    if c["kind"] == "note":
        stem = PurePosixPath(c["note"]).stem
        target = stem + (f"#{c['heading']}" if c.get("heading") else "")
        alias = c.get("alias") or c.get("label") or c.get("heading") or stem
        text = f"[[{target}|{alias}]]"
        if c.get("desc"):
            text += f"\n*{c['desc']}*"
        return text
    return c.get("text", c.get("label", ""))


def _visible(text: str) -> str:
    text = _WIKILINK.sub(lambda m: m.group(2) or m.group(1), text)
    return text.replace("*", "")


def estimate_height(text: str, width: int) -> int:
    """Rendered height of a text card: ~8.2px per character, 24px lines.
    Deliberately a little generous - clipped text is worse than slack."""
    per_line = max(10, int((width - 40) / 8.2))
    lines = sum(max(1, -(-len(line) // per_line)) for line in _visible(text).split("\n"))
    return max(64, -(-(28 + 24 * lines) // 4) * 4)


def _node(kind: str, x: int, y: int, w: int, h: int, **extra) -> dict:
    node = {"id": new_id(), "type": kind, "x": x, "y": y, "width": w, "height": h}
    node.update({k: v for k, v in extra.items() if v is not None})
    return node


def _card_node(card: dict, x: int, y: int, width: int, height: Optional[int] = None) -> dict:
    c = normalize_card(card)
    if c["kind"] == "embed":
        return _node("file", x, y, width, height or 320, file=c["note"], subpath=c.get("subpath"),
                     color=c.get("color"))
    text = card_text(c)
    return _node("text", x, y, width, height or estimate_height(text, width), text=text, color=c.get("color"))


def _pack_cards(cards: List[dict], x0: int, y0: int, width: int, nodes: List[dict], ids: Dict[str, str]) -> int:
    """Masonry into two columns: a normal card goes into the shorter
    column; a wide card (or a long description) spans both. Returns the
    bottom y of the packed block."""
    colw = (width - CARD_GAP) // 2
    ys = [y0, y0]
    for raw in cards:
        c = normalize_card(raw)
        text = card_text(c)
        wide = bool(c.get("wide")) or c["kind"] == "embed" or len(_visible(text)) > 190
        if wide:
            y = max(ys)
            node = _card_node(c, x0, y, width)
            ys = [y + node["height"] + CARD_GAP] * 2
        else:
            i = 0 if ys[0] <= ys[1] else 1
            node = _card_node(c, x0 + i * (colw + CARD_GAP), ys[i], colw)
            ys[i] += node["height"] + CARD_GAP
        nodes.append(node)
        if c.get("id"):
            ids[c["id"]] = node["id"]
    return max(ys) - CARD_GAP


def _stage_header_text(stage: dict) -> str:
    parts = []
    if stage.get("goal"):
        parts.append(f"**Цель:** {stage['goal']}")
    if stage.get("action"):
        parts.append(f"**Делаем:** {stage['action']}")
    if stage.get("expected_result"):
        parts.append(f"**Результат:** {stage['expected_result']}")
    return "\n".join(parts)


def _layout_stage(stage: dict, ids: Dict[str, str]) -> Tuple[List[dict], int]:
    """A stage group with its goal card, cards and nested subgroups,
    positioned from (0, 0). Returns (nodes, height)."""
    nodes: List[dict] = []
    group = _node("group", 0, 0, GROUP_W, 0, label=stage["name"], color=stage.get("color"))
    nodes.append(group)
    ids[stage.get("id") or stage["name"]] = group["id"]
    y = PAD
    header = _stage_header_text(stage)
    if header:
        h = _card_node({"text": header}, PAD, y, INNER_W)
        nodes.append(h)
        y += h["height"] + CARD_GAP
    if stage.get("cards"):
        y = _pack_cards(stage["cards"], PAD, y, INNER_W, nodes, ids) + CARD_GAP
    for sub in stage.get("subgroups", []):
        y += LABEL_SPACE - CARD_GAP if stage.get("cards") or header else LABEL_SPACE
        sg = _node("group", PAD, y, INNER_W, 0, label=sub["name"], color=sub.get("color"))
        nodes.append(sg)
        if sub.get("id"):
            ids[sub["id"]] = sg["id"]
        bottom = _pack_cards(sub.get("cards", []), PAD + SUB_PAD, y + SUB_PAD, INNER_W - 2 * SUB_PAD, nodes, ids)
        sg["height"] = bottom + SUB_PAD - y
        y += sg["height"] + CARD_GAP
    group["height"] = y - CARD_GAP + PAD
    return nodes, group["height"]


def _shift(nodes: List[dict], dx: int, dy: int) -> None:
    for n in nodes:
        n["x"] += dx
        n["y"] += dy


def _bbox(nodes: List[dict]) -> Tuple[int, int, int, int]:
    return (min(n["x"] for n in nodes), min(n["y"] for n in nodes),
            max(n["x"] + n["width"] for n in nodes), max(n["y"] + n["height"] for n in nodes))


def _auto_sides(a: dict, b: dict) -> Tuple[str, str]:
    a_r, b_r = a["x"] + a["width"], b["x"] + b["width"]
    overlap_y = a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["height"]
    if overlap_y:
        return ("right", "left") if b["x"] >= a_r - 1 else ("left", "right") if b_r <= a["x"] + 1 else ("bottom", "top")
    return ("bottom", "top") if b["y"] > a["y"] else ("top", "bottom")


def build_hub_layout(spec: dict) -> Tuple[List[dict], List[dict]]:
    """A fresh HUB canvas in the reference's idiom (HUB RAG 2).

    spec = {
      "stages": [{id?, name, zone?, row?, col?, color?, goal?, action?, expected_result?, next_label?,
                  cards: [card...], subgroups: [{id?, name, color?, cards}]}],
      "controls": [{id, text, color?, near: <stage id>, place: "above"|"below"}],
      "edges": [{from, to, label?, color?}]   # ids of stages/cards/controls/subgroups
      "spine": true,                           # chain consecutive stages
      "legend": {"4": "..."},                  # overrides DEFAULT_LEGEND texts
    }
    Stages with the same `zone` share a macro group; zones stack top to
    bottom, stages inside a zone run left to right and wrap into rows
    after MAX_COLS (or by explicit `row`). Colours of used statuses are
    explained by an auto legend.
    """
    stages = spec.get("stages", [])
    ids: Dict[str, str] = {}
    layouts = []
    for st in stages:
        sn, sh = _layout_stage(st, ids)
        layouts.append((st, sn, sh))

    zone_order: List[Optional[str]] = []
    for st, _, _ in layouts:
        z = st.get("zone")
        if z not in zone_order:
            zone_order.append(z)

    nodes: List[dict] = []
    stage_nodes: Dict[str, dict] = {}
    cursor_y = 0

    used = set()
    for st, sn, _ in layouts:
        for n in sn:
            if n.get("color"):
                used.add(n["color"])
    for c in spec.get("controls", []):
        if c.get("color"):
            used.add(c["color"])
    legend_texts = {**DEFAULT_LEGEND, **spec.get("legend", {})}
    legend_colors = [c for c in sorted(used) if c in legend_texts]
    if legend_colors and not spec.get("no_legend"):
        lg = _node("group", 0, cursor_y, GROUP_W, 0, label="Легенда")
        lnodes = [lg]
        by = _pack_cards([{"text": legend_texts[c], "color": c} for c in legend_colors],
                         PAD, cursor_y + PAD, INNER_W, lnodes, {})
        lg["height"] = by + PAD - cursor_y
        nodes += lnodes
        cursor_y += lg["height"] + LABEL_SPACE + 60

    controls = spec.get("controls", [])
    zone_boxes: Dict[Optional[str], Tuple[int, int]] = {}
    for zi, z in enumerate(zone_order):
        members = [(st, sn, sh) for st, sn, sh in layouts if st.get("zone") == z]
        rows: Dict[int, List] = {}
        auto_row = 0
        for i, m in enumerate(members):
            r = m[0].get("row")
            rows.setdefault(r if r is not None else i // MAX_COLS, []).append(m)
        zone_x = 0
        content_x = zone_x + (ZONE_PAD_X if z else 0)
        # room for controls hanging above this zone / below the previous one
        member_ids = {m[0].get("id") or m[0]["name"] for m in members}
        above = [c for c in controls if c.get("near") in member_ids and c.get("place", "above") == "above"]
        if above:
            cursor_y += max(estimate_height(c["text"], CONTROL_W) for c in above) + 100
        zone_top = cursor_y
        row_y = cursor_y + (ZONE_PAD_TOP if z else 0)
        zone_nodes: List[dict] = []
        for rkey in sorted(rows):
            row = rows[rkey]
            row_h = 0
            for i, (st, sn, sh) in enumerate(row):
                col = st.get("col", i)  # explicit column keeps a loop-back stage right under its source
                _shift(sn, content_x + col * (GROUP_W + STAGE_GAP), row_y)
                zone_nodes += sn
                stage_nodes[st.get("id") or st["name"]] = sn[0]
                row_h = max(row_h, sh)
            row_y += row_h + LABEL_SPACE + 40
        row_y -= LABEL_SPACE + 40
        if z:
            gb = _bbox(zone_nodes)
            zg = _node("group", gb[0] - ZONE_PAD_X, zone_top, gb[2] - gb[0] + 2 * ZONE_PAD_X,
                       gb[3] + ZONE_PAD_BOTTOM - zone_top, label=z)
            nodes.append(zg)
            ids[f"zone:{z}"] = zg["id"]
            zone_bottom = zg["y"] + zg["height"]
        else:
            zone_bottom = row_y
        nodes += zone_nodes
        below = [c for c in controls if c.get("near") in member_ids and c.get("place") == "below"]
        cursor_y = zone_bottom + ZONE_GAP
        if below:
            cursor_y += max(estimate_height(c["text"], CONTROL_W) for c in below) + 100
        zone_boxes[z] = (zone_top, zone_bottom)

    by_id = {n["id"]: n for n in nodes}
    for c in controls:
        near = stage_nodes.get(c.get("near"))
        if near is None:
            continue
        h = estimate_height(c["text"], CONTROL_W)
        zt, zb = zone_boxes[next(st.get("zone") for st, _, _ in layouts if (st.get("id") or st["name"]) == c["near"])]
        cx = near["x"] + (near["width"] - CONTROL_W) // 2
        y = zt - h - 100 if c.get("place", "above") == "above" else zb + 100
        node = _node("text", cx, y, CONTROL_W, h, text=c["text"], color=c.get("color"))
        nodes.append(node)
        ids[c["id"]] = node["id"]
    by_id = {n["id"]: n for n in nodes}

    edges: List[dict] = []

    def add_edge(a_id: str, b_id: str, label=None, color=None):
        a, b = by_id[a_id], by_id[b_id]
        fs, ts = _auto_sides(a, b)
        e = {"id": new_id(), "fromNode": a_id, "fromSide": fs, "toNode": b_id, "toSide": ts}
        if label:
            e["label"] = label
        if color:
            e["color"] = color
        edges.append(e)

    if spec.get("spine", True):
        for i in range(len(stages) - 1):
            add_edge(ids[stages[i].get("id") or stages[i]["name"]],
                     ids[stages[i + 1].get("id") or stages[i + 1]["name"]], stages[i].get("next_label"))
    for e in spec.get("edges", []):
        add_edge(ids[e["from"]], ids[e["to"]], e.get("label"), e.get("color"))
    return nodes, edges


def build_stage_layout(stages: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Compatibility wrapper: a bare stage list is a spec with only stages."""
    return build_hub_layout({"stages": stages})


def canvas_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class CanvasWriteResult:
    status: str  # applied | conflict
    detail: str
    new_hash: Optional[str] = None


def write_canvas(
    vault_path: Path, rel_path: str, nodes: List[dict], edges: List[dict], based_on_hash: Optional[str]
) -> CanvasWriteResult:
    """The Canvas-side write, same propose/apply spirit as
    lib/obsidian_common/patch.py but whole-file: there is no natural
    smaller "region" to scope a hash check to in a flat JSON node/edge
    array the way there is for a Markdown heading (patch.py's EOF-append
    case makes the same whole-file choice for the same reason). Every
    caller here is additive (new nodes/edges appended, nothing existing
    ever mutated - see add_card_near_group/build_stage_layout), so the
    only real conflict this needs to catch is "the file changed since I
    last read it", not "which specific part changed".
    `based_on_hash=None` means "this path must not already exist" (create).
    """
    full = Path(vault_path) / rel_path
    current_text = full.read_text(encoding="utf-8") if full.is_file() else None
    if based_on_hash is None:
        if current_text is not None:
            return CanvasWriteResult("conflict", "file now exists - expected to be new")
    else:
        if current_text is None:
            return CanvasWriteResult("conflict", "file no longer exists")
        if canvas_hash(current_text) != based_on_hash:
            return CanvasWriteResult("conflict", "canvas changed since it was read - re-read and rebuild")
    new_text = serialize_canvas(nodes, edges)
    atomic_write(full, new_text)
    return CanvasWriteResult("applied", f"wrote {len(nodes)} node(s), {len(edges)} edge(s)", canvas_hash(new_text))


def find_group_by_label(nodes: List[dict], label: str) -> Optional[dict]:
    return next((n for n in nodes if n.get("type") == "group" and n.get("label") == label), None)


def add_card_near_group(nodes: List[dict], group: dict, card: dict) -> dict:
    """A new card positioned just below `group`'s bounding box, stacked
    under whatever is already in that overflow area (existing manual
    cards or ones added by a previous call) - H9: preserve every existing
    coordinate and card, add new material *next to* the stage rather than
    resizing into or overlapping it. This does not touch `group` itself.
    """
    gx, gy, gw, gh = group["x"], group["y"], group["width"], group["height"]
    width = min(gw, INNER_W)
    node = _card_node(card, gx, gy + gh + CARD_GAP, width, card.get("height"))
    # Slide down past anything the card would land on - an enclosing zone
    # box, cards from an earlier add-card, a group of the next row - so it
    # never overlaps (H9) and stays as close under the stage as is free.
    moved = True
    while moved:
        moved = False
        for n in nodes:
            if n is group or not all(isinstance(n.get(k), (int, float)) for k in ("x", "y", "width", "height")):
                continue
            if _inter(node, n):
                node["y"] = n["y"] + n["height"] + CARD_GAP
                moved = True
    return node


_SVG_COLORS = {"1": "#e5484d", "2": "#f08a24", "3": "#d9b100", "4": "#30a46c", "5": "#12a594", "6": "#8e4ec6"}


def _wrap(text: str, width: int) -> List[str]:
    per_line = max(10, int((width - 24) / 8.2))
    lines: List[str] = []
    for para in _visible(text).split("\n"):
        words, cur = para.split(" "), ""
        for w in words:
            if cur and len(cur) + 1 + len(w) > per_line:
                lines.append(cur)
                cur = w
            else:
                cur = f"{cur} {w}".strip()
        lines.append(cur)
    return lines


def render_svg(nodes: List[dict], edges: List[dict]) -> str:
    """Standalone SVG of a canvas for a visual check outside Obsidian:
    groups, coloured cards with wrapped text, labelled arrows. Text is
    wrapped with the same width model as `estimate_height`, so clipped
    cards show up here as text running past the card."""
    from xml.sax.saxutils import escape
    if not nodes:
        return '<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"/>'
    x0, y0, x1, y1 = _bbox(nodes)
    m = 60
    by_id = {n["id"]: n for n in nodes}
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0 - m} {y0 - m} {x1 - x0 + 2 * m} {y1 - y0 + 2 * m}" '
           f'width="{x1 - x0 + 2 * m}" height="{y1 - y0 + 2 * m}" font-family="sans-serif" font-size="15">',
           f'<rect x="{x0 - m}" y="{y0 - m}" width="{x1 - x0 + 2 * m}" height="{y1 - y0 + 2 * m}" fill="#1e1e1e"/>',
           '<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" '
           'orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#9a9a9a"/></marker></defs>']
    for n in (n for n in nodes if n.get("type") == "group"):
        col = _SVG_COLORS.get(str(n.get("color")), "#7a7a7a")
        out.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["width"]}" height="{n["height"]}" rx="10" '
                   f'fill="{col}" fill-opacity="0.07" stroke="{col}" stroke-opacity="0.6" stroke-width="2"/>')
        out.append(f'<text x="{n["x"]}" y="{n["y"] - 10}" fill="#bdbdbd" font-size="18">{escape(n.get("label", ""))}</text>')
    for e in edges:
        a, b = by_id.get(e.get("fromNode")), by_id.get(e.get("toNode"))
        if not a or not b:
            continue

        def pt(n, side):
            return {"right": (n["x"] + n["width"], n["y"] + n["height"] / 2), "left": (n["x"], n["y"] + n["height"] / 2),
                    "top": (n["x"] + n["width"] / 2, n["y"]), "bottom": (n["x"] + n["width"] / 2, n["y"] + n["height"])}[side]
        (ax, ay), (bx, by) = pt(a, e.get("fromSide", "right")), pt(b, e.get("toSide", "left"))
        col = _SVG_COLORS.get(str(e.get("color")), "#9a9a9a")
        out.append(f'<line x1="{ax}" y1="{ay}" x2="{bx}" y2="{by}" stroke="{col}" stroke-width="2" marker-end="url(#ar)"/>')
        if e.get("label"):
            out.append(f'<text x="{(ax + bx) / 2}" y="{(ay + by) / 2 - 6}" fill="#e0e0e0" text-anchor="middle" '
                       f'paint-order="stroke" stroke="#1e1e1e" stroke-width="5">{escape(e["label"])}</text>')
    for n in (n for n in nodes if n.get("type") != "group"):
        col = _SVG_COLORS.get(str(n.get("color")), "#8a8a8a")
        out.append(f'<rect x="{n["x"]}" y="{n["y"]}" width="{n["width"]}" height="{n["height"]}" rx="6" '
                   f'fill="{col}" fill-opacity="0.22" stroke="{col}" stroke-width="1.5"/>')
        text = n.get("text") or f"[{n.get('file', '')}]"
        for i, line in enumerate(_wrap(text, n["width"])):
            out.append(f'<text x="{n["x"] + 12}" y="{n["y"] + 24 + 24 * i}" fill="#e8e8e8">{escape(line)}</text>')
    out.append("</svg>")
    return "\n".join(out)
