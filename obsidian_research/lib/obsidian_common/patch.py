"""The propose -> apply engine every write-capable skill (04-07) shares.

Implements ADR-0002 (proposal-first) and algorithms.md §3 step 3: `prepare`
produces a diff plus what it was based on; `apply` re-reads the live file,
checks only the *touched region* is unchanged since propose, writes
atomically, and reports a clear conflict instead of a silent overwrite or a
crash when it isn't. A conflict is an ordinary, expected outcome here, not
an exception - rebuilding the proposal against the live file is the
caller's (Claude's) next step, not a bug.

Checking only the touched region (a section's own text, a managed block's
body, the frontmatter block, one line) rather than the whole file is a
deliberate reading of foundation.md §2.3 rule 12 ("при расхождении
пересобрать правку, сохранив новые пользовательские изменения"): a change
elsewhere in the file - the exact case that rule asks us to preserve -
should not block an unrelated, still-valid edit.

Every op is idempotent by construction: re-running `apply` with the same
Patch against a file that already has the change applied recomputes the
same target content, notices old == new, and reports `unchanged` rather
than writing a duplicate.
"""
from __future__ import annotations

import dataclasses
import json
import re
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

from . import markdown as md
from .frontmatter_ops import merge_frontmatter, serialize_frontmatter
from .write import atomic_write, make_diff, new_change_id, region_hash

BLOCK_ID_RE = re.compile(r"\^([A-Za-z0-9-]+)\s*$")
MANAGED_START_RE = re.compile(
    r"<!--\s*obsidian-skills:managed\s+id=(?P<id>[\w-]+)[^>]*-->\n?"
)
MANAGED_END_TPL = "<!-- /obsidian-skills:managed id={id} -->"


class PatchError(RuntimeError):
    """Propose-time failure: the proposal itself cannot be formed as asked
    (heading not found/ambiguous, target already exists, etc.). Distinct
    from a *conflict*, which is a normal, expected apply-time outcome."""


@dataclasses.dataclass
class Patch:
    change_id: str
    path: str
    op: str
    params: Dict
    based_on: Optional[Dict]  # None only for create_file / no-op ensure_block_id
    preview_diff: str
    reason: Optional[str] = None
    sources: List[str] = dataclasses.field(default_factory=list)
    created_at: float = dataclasses.field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps(dataclasses.asdict(self), ensure_ascii=False, indent=2, default=str)

    @staticmethod
    def from_json(s: str) -> "Patch":
        return Patch(**json.loads(s))


@dataclasses.dataclass
class ChangeRecord:
    change_id: str
    path: str
    operation: str
    status: str  # applied | unchanged | conflict | error
    detail: str
    new_hash: Optional[str] = None

    def to_dict(self) -> Dict:
        return dataclasses.asdict(self)


def _read(vault_path: Path, rel_path: str) -> str:
    full = Path(vault_path) / rel_path
    if not full.is_file():
        raise PatchError(f"not_found: {rel_path}")
    return md.read_text(full)


def _resolve_heading(headings, heading_query: str):
    matches = md.find_heading(headings, heading_query)
    if not matches:
        raise PatchError(f"heading_not_found: {heading_query!r}")
    if len(matches) > 1:
        candidates = [" > ".join(h.path) for h in matches]
        raise PatchError(
            f"heading_ambiguous: {heading_query!r} matches {candidates}; "
            "disambiguate with 'Parent > Child'"
        )
    return matches[0]


# --------------------------------------------------------------------------
# propose_*
# --------------------------------------------------------------------------

def propose_create_file(
    vault_path: Path, rel_path: str, content: str, reason: str = "", sources=None
) -> Patch:
    full = Path(vault_path) / rel_path
    if full.exists():
        raise PatchError(
            f"already_exists: {rel_path} - use obsidian-revise to change an "
            "existing file, obsidian-author only creates new ones"
        )
    diff = make_diff("", content, rel_path)
    return Patch(
        new_change_id(), rel_path, "create_file", {"content": content},
        based_on={"kind": "not_exists"}, preview_diff=diff,
        reason=reason, sources=sources or [],
    )


def propose_replace_section(
    vault_path: Path, rel_path: str, heading_query: str, new_text: str,
    reason: str = "", sources=None,
) -> Patch:
    raw = _read(vault_path, rel_path)
    parsed = md.parse_frontmatter(raw)
    headings = md.parse_headings(parsed.body, parsed.body_start_line)
    heading = _resolve_heading(headings, heading_query)
    old_text = md.own_text(raw, headings, heading)
    diff = make_diff(old_text, new_text, f"{rel_path}#{heading_query}")
    return Patch(
        new_change_id(), rel_path, "replace_section",
        {"heading_query": heading_query, "new_text": new_text},
        based_on={"kind": "section", "heading_path": list(heading.path),
                  "hash": region_hash(old_text)},
        preview_diff=diff, reason=reason, sources=sources or [],
    )


def propose_append_section(
    vault_path: Path, rel_path: str, heading_query: str, addition: str,
    create_if_missing: bool = True, reason: str = "", sources=None,
) -> Patch:
    raw = _read(vault_path, rel_path)
    parsed = md.parse_frontmatter(raw)
    headings = md.parse_headings(parsed.body, parsed.body_start_line)
    matches = md.find_heading(headings, heading_query)
    if len(matches) > 1:
        candidates = [" > ".join(h.path) for h in matches]
        raise PatchError(f"heading_ambiguous: {heading_query!r} matches {candidates}")
    if matches:
        heading = matches[0]
        old_text = md.own_text(raw, headings, heading)
        new_text = old_text.rstrip("\n") + "\n\n" + addition.strip() + "\n"
        diff = make_diff(old_text, new_text, f"{rel_path}#{heading_query}")
        return Patch(
            new_change_id(), rel_path, "append_section",
            {"heading_query": heading_query, "addition": addition, "create_if_missing": create_if_missing},
            based_on={"kind": "section", "heading_path": list(heading.path), "hash": region_hash(old_text)},
            preview_diff=diff, reason=reason, sources=sources or [],
        )
    if not create_if_missing:
        raise PatchError(f"heading_not_found: {heading_query!r}")
    new_block = f"\n## {heading_query}\n\n{addition.strip()}\n"
    diff = make_diff("", new_block, f"{rel_path}#{heading_query} (new)")
    return Patch(
        new_change_id(), rel_path, "append_section",
        {"heading_query": heading_query, "addition": addition, "create_if_missing": create_if_missing},
        based_on={"kind": "eof", "hash": region_hash(raw)},
        preview_diff=diff, reason=reason, sources=sources or [],
    )


def propose_managed_block(
    vault_path: Path, rel_path: str, block_id: str, new_body: str, skill_name: str,
    anchor_heading: Optional[str] = None, reason: str = "", sources=None,
) -> Patch:
    raw = _read(vault_path, rel_path)
    existing = _find_managed_block(raw, block_id)
    if existing:
        _, _, old_body = existing
        diff = make_diff(old_body, new_body, f"{rel_path}#managed:{block_id}")
        based_on = {"kind": "managed_block", "block_id": block_id, "hash": region_hash(old_body)}
    else:
        diff = make_diff("", new_body, f"{rel_path}#managed:{block_id} (new)")
        if anchor_heading:
            parsed = md.parse_frontmatter(raw)
            headings = md.parse_headings(parsed.body, parsed.body_start_line)
            heading = _resolve_heading(headings, anchor_heading)
            anchor_text = md.own_text(raw, headings, heading)
            based_on = {"kind": "managed_block_new_anchored", "anchor_heading": anchor_heading,
                        "anchor_heading_path": list(heading.path), "hash": region_hash(anchor_text)}
        else:
            based_on = {"kind": "managed_block_new_eof", "hash": region_hash(raw)}
    return Patch(
        new_change_id(), rel_path, "managed_block",
        {"block_id": block_id, "new_body": new_body, "skill_name": skill_name,
         "anchor_heading": anchor_heading},
        based_on=based_on, preview_diff=diff, reason=reason, sources=sources or [],
    )


def propose_yaml_merge(
    vault_path: Path, rel_path: str, updates: Dict, reason: str = "", sources=None,
) -> Patch:
    raw = _read(vault_path, rel_path)
    parsed = md.parse_frontmatter(raw)
    if parsed.meta_error:
        raise PatchError(f"unparsable_frontmatter: {parsed.meta_error}")
    old_fm_block = serialize_frontmatter(parsed.meta) if parsed.body_start_line > 1 else "---\n---\n"
    merged = merge_frontmatter(parsed.meta, updates)
    new_fm_block = serialize_frontmatter(merged)
    diff = make_diff(old_fm_block, new_fm_block, f"{rel_path}#frontmatter")
    return Patch(
        new_change_id(), rel_path, "yaml_merge", {"updates": updates},
        based_on={"kind": "frontmatter", "hash": region_hash(old_fm_block)},
        preview_diff=diff, reason=reason, sources=sources or [],
    )


def propose_ensure_block_id(
    vault_path: Path, rel_path: str, heading_query: str, paragraph_substring: str,
    reason: str = "",
) -> Patch:
    raw = _read(vault_path, rel_path)
    parsed = md.parse_frontmatter(raw)
    headings = md.parse_headings(parsed.body, parsed.body_start_line)
    heading = _resolve_heading(headings, heading_query)
    lines = raw.splitlines()
    target_idx = None
    for i in range(heading.line_start - 1, heading.line_end - 1):
        if i < len(lines) and paragraph_substring in lines[i]:
            target_idx = i
            break
    if target_idx is None:
        raise PatchError(
            f"paragraph_not_found: {paragraph_substring!r} under heading {heading_query!r}"
        )
    existing_id_match = BLOCK_ID_RE.search(lines[target_idx])
    if existing_id_match:
        return Patch(
            new_change_id(), rel_path, "ensure_block_id",
            {"existing_id": existing_id_match.group(1)}, based_on=None,
            preview_diff="", reason=reason or "block id already present",
        )
    used_ids = set(BLOCK_ID_RE.findall(raw))
    new_id = _new_block_id(used_ids)
    diff = make_diff(lines[target_idx], f"{lines[target_idx]} ^{new_id}", f"{rel_path}:{target_idx + 1}")
    return Patch(
        new_change_id(), rel_path, "ensure_block_id",
        {"heading_query": heading_query, "paragraph_substring": paragraph_substring, "new_id": new_id},
        based_on={"kind": "line", "line_no": target_idx + 1, "hash": region_hash(lines[target_idx])},
        preview_diff=diff, reason=reason,
    )


def _new_block_id(used_ids: set) -> str:
    for _ in range(1000):
        candidate = uuid.uuid4().hex[:6]
        if candidate not in used_ids:
            return candidate
    raise PatchError("could_not_allocate_block_id")


def _find_managed_block(raw: str, block_id: str):
    """Returns (start_char, end_char, body) for the block with this exact
    id, or None. Body excludes both marker lines."""
    for m in MANAGED_START_RE.finditer(raw):
        if m.group("id") != block_id:
            continue
        end_marker = MANAGED_END_TPL.format(id=block_id)
        end_idx = raw.find(end_marker, m.end())
        if end_idx == -1:
            continue
        return m.start(), end_idx + len(end_marker), raw[m.end():end_idx]
    return None


# --------------------------------------------------------------------------
# apply
# --------------------------------------------------------------------------

def apply_patch(vault_path: Path, patch: Patch) -> ChangeRecord:
    try:
        dispatch = {
            "create_file": _apply_create_file,
            "replace_section": _apply_replace_section,
            "append_section": _apply_append_section,
            "managed_block": _apply_managed_block,
            "yaml_merge": _apply_yaml_merge,
            "ensure_block_id": _apply_ensure_block_id,
        }[patch.op]
    except KeyError:
        return ChangeRecord(patch.change_id, patch.path, patch.op, "error", f"unknown op {patch.op!r}")
    try:
        return dispatch(vault_path, patch)
    except PatchError as exc:
        return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict", str(exc))


def _splice_lines(lines: List[str], start_idx: int, end_idx: int, new_content_lines: List[str]) -> List[str]:
    """Replace lines[start_idx:end_idx] with new_content_lines, adding one
    blank separator line before whatever follows if there is a next line
    and the new content doesn't already end on a blank one - otherwise a
    caller-supplied replacement that (unlike the original own_text) has no
    trailing blank line would visually run into the next heading."""
    tail = lines[end_idx:]
    content = list(new_content_lines)
    if tail and content and content[-1].strip() != "":
        content.append("")
    return lines[:start_idx] + content + tail


def _apply_create_file(vault_path: Path, patch: Patch) -> ChangeRecord:
    full = Path(vault_path) / patch.path
    if full.exists():
        return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict",
                             "file now exists - someone/something created it since propose")
    content = patch.params["content"]
    atomic_write(full, content)
    return ChangeRecord(patch.change_id, patch.path, patch.op, "applied",
                         f"created ({len(content)} chars)", region_hash(content))


def _apply_replace_section(vault_path: Path, patch: Patch) -> ChangeRecord:
    raw = _read(vault_path, patch.path)
    parsed = md.parse_frontmatter(raw)
    headings = md.parse_headings(parsed.body, parsed.body_start_line)
    heading = _resolve_heading(headings, patch.params["heading_query"])
    current_text = md.own_text(raw, headings, heading)
    if region_hash(current_text) != patch.based_on["hash"]:
        return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict",
                             "section changed since propose - rebuild the patch against the live file")
    new_text = patch.params["new_text"]
    if current_text == new_text:
        return ChangeRecord(patch.change_id, patch.path, patch.op, "unchanged",
                             "target text already matches", region_hash(raw))
    child_start = heading.line_end
    for h in headings:
        if heading.line_start < h.line_start < heading.line_end:
            child_start = h.line_start
            break
    lines = raw.splitlines()
    new_lines = _splice_lines(lines, heading.line_start - 1, child_start - 1, new_text.splitlines())
    new_raw = "\n".join(new_lines) + ("\n" if raw.endswith("\n") else "")
    atomic_write(Path(vault_path) / patch.path, new_raw)
    return ChangeRecord(patch.change_id, patch.path, patch.op, "applied",
                         f"replaced section {patch.params['heading_query']!r}", region_hash(new_raw))


def _apply_append_section(vault_path: Path, patch: Patch) -> ChangeRecord:
    raw = _read(vault_path, patch.path)
    parsed = md.parse_frontmatter(raw)
    headings = md.parse_headings(parsed.body, parsed.body_start_line)
    matches = md.find_heading(headings, patch.params["heading_query"])
    addition = patch.params["addition"].strip()

    if matches:
        heading = matches[0]
        current_text = md.own_text(raw, headings, heading)
        if patch.based_on.get("kind") != "section" or region_hash(current_text) != patch.based_on.get("hash"):
            return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict",
                                 "section changed since propose (or was created concurrently) - rebuild the patch")
        if addition and addition in current_text:
            return ChangeRecord(patch.change_id, patch.path, patch.op, "unchanged",
                                 "addition already present in section", region_hash(raw))
        new_text = current_text.rstrip("\n") + "\n\n" + addition + "\n"
        child_start = heading.line_end
        for h in headings:
            if heading.line_start < h.line_start < heading.line_end:
                child_start = h.line_start
                break
        lines = raw.splitlines()
        new_lines = _splice_lines(lines, heading.line_start - 1, child_start - 1, new_text.splitlines())
        new_raw = "\n".join(new_lines) + ("\n" if raw.endswith("\n") else "")
        atomic_write(Path(vault_path) / patch.path, new_raw)
        return ChangeRecord(patch.change_id, patch.path, patch.op, "applied",
                             f"appended to section {patch.params['heading_query']!r}", region_hash(new_raw))

    if not patch.params.get("create_if_missing", True):
        return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict", "heading not found")
    if patch.based_on.get("kind") != "eof" or region_hash(raw) != patch.based_on.get("hash"):
        return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict",
                             "file changed since propose - rebuild the patch")
    new_block = f"\n## {patch.params['heading_query']}\n\n{addition}\n"
    new_raw = raw.rstrip("\n") + "\n" + new_block
    atomic_write(Path(vault_path) / patch.path, new_raw)
    return ChangeRecord(patch.change_id, patch.path, patch.op, "applied",
                         f"created new section {patch.params['heading_query']!r}", region_hash(new_raw))


def _apply_managed_block(vault_path: Path, patch: Patch) -> ChangeRecord:
    raw = _read(vault_path, patch.path)
    block_id = patch.params["block_id"]
    new_body = patch.params["new_body"]
    skill_name = patch.params["skill_name"]
    existing = _find_managed_block(raw, block_id)

    if existing:
        start, end, old_body = existing
        if patch.based_on.get("kind") != "managed_block" or region_hash(old_body) != patch.based_on.get("hash"):
            return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict",
                                 "managed block changed since propose - rebuild the patch")
        if old_body.strip() == new_body.strip():
            return ChangeRecord(patch.change_id, patch.path, patch.op, "unchanged",
                                 "block body already matches", region_hash(raw))
        new_raw = _rebuild_managed(raw, start, end, new_body, block_id, skill_name)
        atomic_write(Path(vault_path) / patch.path, new_raw)
        return ChangeRecord(patch.change_id, patch.path, patch.op, "applied",
                             f"updated managed block {block_id}", region_hash(new_raw))

    if patch.based_on.get("kind") == "managed_block_new_anchored":
        parsed = md.parse_frontmatter(raw)
        headings = md.parse_headings(parsed.body, parsed.body_start_line)
        anchor_matches = md.find_heading(headings, patch.params["anchor_heading"])
        if not anchor_matches:
            return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict", "anchor heading no longer found")
        # Content hash below is the real freshness check; if the heading
        # moved to a different parent but its own text is still exactly
        # what propose saw, inserting after it is still correct and safe.
        heading = anchor_matches[0]
        anchor_text = md.own_text(raw, headings, heading)
        if region_hash(anchor_text) != patch.based_on["hash"]:
            return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict",
                                 "anchor section changed since propose - rebuild the patch")
        block_text = _render_managed_block(block_id, new_body, skill_name)
        lines = raw.splitlines()
        insert_at = heading.line_start  # right after the heading line itself
        new_lines = _splice_lines(lines, insert_at, insert_at, block_text.splitlines())
        new_raw = "\n".join(new_lines) + ("\n" if raw.endswith("\n") else "")
        atomic_write(Path(vault_path) / patch.path, new_raw)
        return ChangeRecord(patch.change_id, patch.path, patch.op, "applied",
                             f"inserted managed block {block_id} after {patch.params['anchor_heading']!r}",
                             region_hash(new_raw))

    if region_hash(raw) != patch.based_on.get("hash"):
        return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict",
                             "file changed since propose - rebuild the patch")
    block_text = _render_managed_block(block_id, new_body, skill_name)
    new_raw = raw.rstrip("\n") + "\n\n" + block_text
    atomic_write(Path(vault_path) / patch.path, new_raw)
    return ChangeRecord(patch.change_id, patch.path, patch.op, "applied",
                         f"appended managed block {block_id} at end of file", region_hash(new_raw))


def _render_managed_block(block_id: str, body: str, skill_name: str) -> str:
    return (
        f"<!-- obsidian-skills:managed id={block_id} skill={skill_name} -->\n"
        f"{body.strip()}\n"
        f"{MANAGED_END_TPL.format(id=block_id)}\n"
    )


def _rebuild_managed(raw: str, start: int, end: int, new_body: str, block_id: str, skill_name: str) -> str:
    """start/end are the char offsets `_find_managed_block` returned: start
    is the beginning of the *opening* marker line, end is right after the
    *closing* marker's text (before its own trailing newline). Regenerate
    the whole block including both markers - splicing in only the bare
    body would drop the markers and make the block unfindable next time
    (exactly the duplicate-block bug this function exists to avoid)."""
    remainder = raw[end:]
    if remainder.startswith("\n"):
        remainder = remainder[1:]  # the old closing marker's own newline
    return raw[:start] + _render_managed_block(block_id, new_body, skill_name) + remainder


def _apply_yaml_merge(vault_path: Path, patch: Patch) -> ChangeRecord:
    raw = _read(vault_path, patch.path)
    parsed = md.parse_frontmatter(raw)
    if parsed.meta_error:
        return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict",
                             f"frontmatter is no longer parsable: {parsed.meta_error}")
    old_fm_block = serialize_frontmatter(parsed.meta) if parsed.body_start_line > 1 else "---\n---\n"
    if region_hash(old_fm_block) != patch.based_on["hash"]:
        return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict",
                             "frontmatter changed since propose - rebuild the patch")
    merged = merge_frontmatter(parsed.meta, patch.params["updates"])
    new_fm_block = serialize_frontmatter(merged)
    if new_fm_block == old_fm_block:
        return ChangeRecord(patch.change_id, patch.path, patch.op, "unchanged",
                             "frontmatter already matches", region_hash(raw))
    new_raw = new_fm_block + parsed.body
    atomic_write(Path(vault_path) / patch.path, new_raw)
    return ChangeRecord(patch.change_id, patch.path, patch.op, "applied",
                         "frontmatter merged", region_hash(new_raw))


def _apply_ensure_block_id(vault_path: Path, patch: Patch) -> ChangeRecord:
    if patch.based_on is None:
        return ChangeRecord(patch.change_id, patch.path, patch.op, "unchanged",
                             f"block id already present: ^{patch.params['existing_id']}")
    raw = _read(vault_path, patch.path)
    lines = raw.splitlines()
    line_no = patch.based_on["line_no"]
    if line_no > len(lines) or region_hash(lines[line_no - 1]) != patch.based_on["hash"]:
        return ChangeRecord(patch.change_id, patch.path, patch.op, "conflict",
                             "target line changed since propose - rebuild the patch")
    if BLOCK_ID_RE.search(lines[line_no - 1]):
        return ChangeRecord(patch.change_id, patch.path, patch.op, "unchanged",
                             "a block id was added concurrently", region_hash(raw))
    lines[line_no - 1] = f"{lines[line_no - 1]} ^{patch.params['new_id']}"
    new_raw = "\n".join(lines) + ("\n" if raw.endswith("\n") else "")
    atomic_write(Path(vault_path) / patch.path, new_raw)
    return ChangeRecord(patch.change_id, patch.path, patch.op, "applied",
                         f"assigned ^{patch.params['new_id']}", region_hash(new_raw))
