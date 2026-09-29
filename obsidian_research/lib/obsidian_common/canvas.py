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
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .write import atomic_write

VALID_NODE_TYPES = {"text", "file", "link", "group"}

# Layout constants for a freshly generated HUB (H7: left to right; H4:
# stage = goal blurb + file cards). Not configurable per call on purpose -
# consistent geometry across generated HUBs is more valuable than
# per-call tuning, and an existing HUB's own manual layout is never
# touched by these (see add_card_near_group / H9).
STAGE_WIDTH = 420
STAGE_GAP = 80
CARD_HEIGHT = 80
CARD_GAP = 20
STAGE_HEADER_HEIGHT = 120
STAGE_PADDING = 20


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


def validate_canvas(vault_path: Path, nodes: List[dict], edges: List[dict]) -> List[CanvasIssue]:
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
    return issues


def _card_node(kind: str, x: int, y: int, width: int, height: int, card: dict) -> dict:
    node = {"id": new_id(), "type": kind, "x": x, "y": y, "width": width, "height": height}
    if kind == "file":
        node["file"] = card["file"]
        if card.get("subpath"):
            node["subpath"] = card["subpath"]
    else:
        node["text"] = card.get("text", card.get("label", ""))
    return node


def build_stage_layout(stages: List[dict]) -> Tuple[List[dict], List[dict]]:
    """Fresh left-to-right HUB canvas (H7 default) for a brand-new HUB:
    one group per stage with a text card for its goal and file cards
    stacked below, and a sequential 'next' spine between consecutive
    stages (H8 default main spine; branch/alternative/prerequisite/return
    edges are for the caller to add explicitly via extra_edges, this
    function only builds the default sequential backbone).

    `stages`: [{"name", "goal", "cards": [{"kind": "file"|"text",
    "file"/"text", "subpath"?}]}]
    """
    nodes: List[dict] = []
    edges: List[dict] = []
    x = 0
    stage_group_ids = []
    for stage in stages:
        cards = stage.get("cards", [])
        height = STAGE_HEADER_HEIGHT + STAGE_PADDING + len(cards) * (CARD_HEIGHT + CARD_GAP)
        width = STAGE_WIDTH
        group_id = new_id()
        nodes.append({"id": group_id, "type": "group", "x": x, "y": 0,
                      "width": width, "height": max(height, STAGE_HEADER_HEIGHT), "label": stage["name"]})
        stage_group_ids.append(group_id)
        if stage.get("goal"):
            nodes.append(_card_node("text", x + STAGE_PADDING, STAGE_PADDING,
                                     width - 2 * STAGE_PADDING, STAGE_HEADER_HEIGHT - STAGE_PADDING,
                                     {"text": stage["goal"]}))
        card_y = STAGE_HEADER_HEIGHT + STAGE_PADDING
        for card in cards:
            nodes.append(_card_node(card.get("kind", "file"), x + STAGE_PADDING, card_y,
                                     width - 2 * STAGE_PADDING, CARD_HEIGHT, card))
            card_y += CARD_HEIGHT + CARD_GAP
        x += width + STAGE_GAP

    for i in range(len(stage_group_ids) - 1):
        edges.append({"id": new_id(), "fromNode": stage_group_ids[i], "fromSide": "right",
                       "toNode": stage_group_ids[i + 1], "toSide": "left", "label": "next"})
    return nodes, edges


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
    overflow_bottom = gy + gh
    for n in nodes:
        if n is group:
            continue
        nx, ny, nw, nh = n.get("x", 0), n.get("y", 0), n.get("width", 0), n.get("height", 0)
        overlaps_x = nx < gx + gw and nx + nw > gx
        below_group = ny >= gy + gh - 1
        if overlaps_x and below_group:
            overflow_bottom = max(overflow_bottom, ny + nh)
    y = overflow_bottom + CARD_GAP
    return _card_node(card.get("kind", "file"), gx, y, gw, card.get("height", CARD_HEIGHT), card)
