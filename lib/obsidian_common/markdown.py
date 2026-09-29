"""Markdown parsing: frontmatter, headings, paragraphs, wikilinks, fragments.

This is the "addressed reading" primitive the spec keeps assuming exists
(foundation.md §2.6, algorithms.md §2 "Индексация Markdown и fragment
reader", ADR-0001). Skills 13-18 (RAPTOR/semantic search/index-sync) are not
built yet, so there is no vector index to resolve an address - this module
is the direct, always-correct fallback: it re-parses the live Markdown file
by heading boundaries every time. That matches invariant #1 in CLAUDE.md
("Исходный Markdown — источник истины") by construction, at the cost of not
scaling to semantic ("close in meaning") lookups - that gap is exactly what
skill 13 will add on top of this later, not replace.

Heading boundaries take priority over blind token chunking (defaults.md
§11 "Unit"), and a fenced code block or callout is never split by a blank
line inside it.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

import yaml

FENCE_RE = re.compile(r"^(```+|~~~+)")
HEADING_RE = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
CALLOUT_RE = re.compile(r"^>\s*\[!([A-Za-z]+)\][+-]?\s*(.*)$")
WIKILINK_RE = re.compile(
    r"(?P<embed>!)?\[\[(?P<target>[^\]|#^]+?)"
    r"(?:#(?P<blockmark>\^)?(?P<anchor>[^\]|]+))?"
    r"(?:\|(?P<alias>[^\]]+))?\]\]"
)


def read_text(path: Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace")


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


@dataclass
class ParsedNote:
    meta: dict
    meta_error: Optional[str]
    body: str
    body_start_line: int  # 1-indexed line where body starts in the full file
    raw_text: str


def parse_frontmatter(raw_text: str) -> ParsedNote:
    lines = raw_text.splitlines()
    if lines[:1] != ["---"]:
        return ParsedNote({}, None, raw_text, 1, raw_text)
    end_idx = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end_idx = i
            break
    if end_idx is None:
        return ParsedNote({}, "unterminated frontmatter block", raw_text, 1, raw_text)
    fm_text = "\n".join(lines[1:end_idx])
    try:
        meta = yaml.safe_load(fm_text)
        if not isinstance(meta, dict):
            meta = {} if meta is None else {"_value": meta}
        meta_error = None
    except yaml.YAMLError as exc:
        meta = {}
        meta_error = f"invalid YAML frontmatter: {exc}"
    body_start_line = end_idx + 2  # 1-indexed line after the closing '---'
    body = "\n".join(lines[end_idx + 1:])
    return ParsedNote(meta, meta_error, body, body_start_line, raw_text)


@dataclass
class Heading:
    level: int
    title: str
    line_start: int  # 1-indexed, within the same numbering as the full file
    line_end: int  # exclusive
    path: tuple  # ancestor titles including this heading


def parse_headings(body: str, body_start_line: int = 1) -> List[Heading]:
    lines = body.splitlines()
    raw: List[Heading] = []
    in_fence = False
    fence_marker = None
    stack: List[str] = []
    for i, line in enumerate(lines):
        fm = FENCE_RE.match(line.strip())
        if fm:
            marker = fm.group(1)[0] * 3
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif line.strip().startswith(fence_marker):
                in_fence = False
                fence_marker = None
            continue
        if in_fence:
            continue
        hm = HEADING_RE.match(line)
        if not hm:
            continue
        level = len(hm.group(1))
        title = hm.group(2).strip()
        stack = stack[: level - 1]
        stack.append(title)
        raw.append(
            Heading(
                level=level,
                title=title,
                line_start=body_start_line + i,
                line_end=-1,  # filled below
                path=tuple(stack),
            )
        )
    # resolve line_end: next heading with level <= this one, else EOF
    total_lines = body_start_line + len(lines)
    for idx, h in enumerate(raw):
        end = total_lines
        for later in raw[idx + 1:]:
            if later.level <= h.level:
                end = later.line_start
                break
        raw[idx] = Heading(h.level, h.title, h.line_start, end, h.path)
    return raw


def slice_lines(raw_text: str, line_start: int, line_end: int) -> str:
    """1-indexed, line_end exclusive, against the *whole file* line numbering."""
    lines = raw_text.splitlines()
    return "\n".join(lines[line_start - 1: line_end - 1])


def own_text(raw_text: str, headings: List[Heading], heading: Heading) -> str:
    """This heading's text, stopping at its first child sub-heading."""
    child_start = heading.line_end
    for h in headings:
        if h.line_start > heading.line_start and h.line_start < heading.line_end:
            child_start = h.line_start
            break
    return slice_lines(raw_text, heading.line_start, child_start)


def find_heading(headings: List[Heading], query: str) -> List[Heading]:
    """Match a heading by title, or a ' > '-separated ancestor chain.

    Obsidian itself resolves [[Note#Heading]] by heading text alone (it does
    not require the full ancestor chain), so a bare title is accepted; the
    ' > ' chain form is offered for disambiguating duplicate heading text,
    which real vaults do have (e.g. repeated "## Пример" sections).
    """
    query = query.strip()
    if ">" in query:
        chain = tuple(part.strip() for part in query.split(">"))
        return [h for h in headings if h.path[-len(chain):] == chain]
    return [h for h in headings if h.title.strip().casefold() == query.casefold()]


def extract_summary_suti(raw_text: str, headings: List[Heading]) -> Optional[str]:
    """REQ-KNO-0001: new articles carry a two-sentence '## Суть' right after
    the frontmatter. Returns its own text (without the heading line) if
    present; None for older articles that predate the rule - callers must
    fall back to normal progressive retrieval for those, not fabricate one.
    """
    matches = find_heading(headings, "Суть")
    if not matches:
        return None
    h = matches[0]
    text = own_text(raw_text, headings, h)
    lines = text.splitlines()
    return "\n".join(lines[1:]).strip() if lines else ""


PARA_BREAK_RE = re.compile(r"^\s*$")


def split_paragraphs(text: str) -> List[str]:
    """Blank-line-delimited paragraphs, keeping fences/callouts atomic."""
    lines = text.splitlines()
    paras: List[str] = []
    buf: List[str] = []
    in_fence = False
    fence_marker = None
    in_callout = False

    def flush():
        if buf:
            joined = "\n".join(buf).strip("\n")
            if joined.strip():
                paras.append(joined)
            buf.clear()

    for line in lines:
        stripped = line.strip()
        fm = FENCE_RE.match(stripped)
        if fm:
            marker = fm.group(1)[0] * 3
            if not in_fence:
                in_fence = True
                fence_marker = marker
                buf.append(line)
            elif stripped.startswith(fence_marker):
                buf.append(line)
                in_fence = False
                fence_marker = None
            continue
        if in_fence:
            buf.append(line)
            continue
        if stripped.startswith(">"):
            if not in_callout and buf and not buf[-1].strip().startswith(">"):
                flush()
            in_callout = True
            buf.append(line)
            continue
        in_callout = False
        if PARA_BREAK_RE.match(line):
            flush()
            continue
        buf.append(line)
    flush()
    return paras


@dataclass
class WikiLink:
    target: str  # note name/path as written, not yet resolved to a real file
    anchor: Optional[str]  # heading text, or block id if is_block
    is_block: bool
    alias: Optional[str]
    is_embed: bool
    line: int  # 1-indexed line in the file where the link occurs


def extract_wikilinks(raw_text: str) -> List[WikiLink]:
    out = []
    for lineno, line in enumerate(raw_text.splitlines(), start=1):
        for m in WIKILINK_RE.finditer(line):
            out.append(
                WikiLink(
                    target=m.group("target").strip(),
                    anchor=m.group("anchor"),
                    is_block=bool(m.group("blockmark")),
                    alias=m.group("alias").strip() if m.group("alias") else None,
                    is_embed=bool(m.group("embed")),
                    line=lineno,
                )
            )
    return out


# frontmatter fields the spec treats as structural relations, not free text
# (data-model.md §4.1/4.2/4.3): topics, sources, moc, hub, parent_mocs,
# related_mocs, canvas.
FRONTMATTER_LINK_FIELDS = (
    "topics",
    "sources",
    "moc",
    "hub",
    "parent_mocs",
    "related_mocs",
    "canvas",
)


@dataclass
class FrontmatterLink:
    field: str
    target: str
    anchor: Optional[str]


def extract_frontmatter_links(meta: dict) -> List[FrontmatterLink]:
    out: List[FrontmatterLink] = []
    for field_name in FRONTMATTER_LINK_FIELDS:
        if field_name not in meta:
            continue
        value = meta[field_name]
        values = value if isinstance(value, list) else [value]
        for v in values:
            if not isinstance(v, str):
                continue
            for m in WIKILINK_RE.finditer(v):
                out.append(
                    FrontmatterLink(
                        field=field_name,
                        target=m.group("target").strip(),
                        anchor=m.group("anchor"),
                    )
                )
    return out


@dataclass
class FragmentResult:
    status: str  # resolved | not_found | needs_context | out_of_scope
    path: str
    heading_path: Optional[list]
    line_start: Optional[int]
    line_end: Optional[int]
    text: Optional[str]
    content_hash: Optional[str]
    candidates: Optional[list] = None  # for needs_context: ambiguous titles


def read_fragment(
    vault_path: Path, rel_path: str, heading_query: Optional[str] = None
) -> FragmentResult:
    full_path = Path(vault_path) / rel_path
    if not full_path.is_file():
        return FragmentResult("not_found", rel_path, None, None, None, None, None)
    raw = read_text(full_path)
    parsed = parse_frontmatter(raw)
    headings = parse_headings(parsed.body, parsed.body_start_line)

    if heading_query is None:
        return FragmentResult(
            "resolved",
            rel_path,
            None,
            1,
            len(raw.splitlines()) + 1,
            raw,
            content_hash(raw),
        )

    matches = find_heading(headings, heading_query)
    if not matches:
        return FragmentResult("not_found", rel_path, None, None, None, None, None)
    if len(matches) > 1:
        return FragmentResult(
            "needs_context",
            rel_path,
            None,
            None,
            None,
            None,
            None,
            candidates=[" > ".join(h.path) for h in matches],
        )
    h = matches[0]
    text = own_text(raw, headings, h)
    return FragmentResult(
        "resolved",
        rel_path,
        list(h.path),
        h.line_start,
        h.line_end,
        text,
        content_hash(text),
    )
