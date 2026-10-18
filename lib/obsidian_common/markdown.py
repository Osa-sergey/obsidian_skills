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
# End-of-line Obsidian block reference, e.g. "...text ^abc123". Canonical
# here (markdown syntax); patch.py imports it rather than redefining it.
BLOCK_ID_RE = re.compile(r"\^([A-Za-z0-9-]+)\s*$")
# `target` allows zero characters so a same-file link like [[#Heading]] or
# [[#^blockid]] (no note name before the '#') still matches - Obsidian
# treats an empty target as "this file"; resolve_link_target below turns
# that into the source path itself rather than reporting not_found.
WIKILINK_RE = re.compile(
    r"(?P<embed>!)?\[\[(?P<target>[^\]|#^]*?)"
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


def fence_mask(lines: List[str]) -> List[bool]:
    """True at index i if lines[i] is inside (or is a delimiter of) a ``` or
    ~~~ fenced code block. Shared by parse_headings (a `#` in a code sample
    is not a heading) and extract_wikilinks (a `[[...]]`-shaped template
    placeholder inside a ```dataviewjs block, e.g. `[[${m.file.path}]]`, is
    not a real link - real vaults have these, and treating one as a graph
    edge or a broken link is a false positive, not caution)."""
    mask = [False] * len(lines)
    in_fence = False
    fence_marker = None
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
            mask[i] = True
            continue
        mask[i] = in_fence
    return mask


def parse_headings(body: str, body_start_line: int = 1) -> List[Heading]:
    lines = body.splitlines()
    raw: List[Heading] = []
    in_fence_mask = fence_mask(lines)
    # (level, title) pairs for the currently open ancestor chain. Truncating
    # by *level value*, not by stack length, is what makes this correct
    # when a document skips levels or - very common in this vault, where a
    # note's body starts straight at '##' with no '#' title - never opens
    # at H1 at all: a stack-length-based truncation (`stack[:level-1]`)
    # silently treats a previous *sibling* at the same level as if it were
    # a kept ancestor whenever the stack's length already happens to equal
    # level-1, producing a wrong, too-deep `path` for every heading after
    # the first at that level.
    stack: List[tuple] = []
    for i, line in enumerate(lines):
        if in_fence_mask[i]:
            continue
        hm = HEADING_RE.match(line)
        if not hm:
            continue
        level = len(hm.group(1))
        title = hm.group(2).strip()
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        raw.append(
            Heading(
                level=level,
                title=title,
                line_start=body_start_line + i,
                line_end=-1,  # filled below
                path=tuple(t for _, t in stack),
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


def section_end_line(headings: List[Heading], heading: Heading, child_depth: int = 0) -> int:
    """The exclusive end line for `heading`'s own text plus up to
    `child_depth` levels of descendant subsections (0 = stop at the first
    child heading of any depth, i.e. own_text's boundary). Stops at the
    first descendant whose relative depth exceeds child_depth and does not
    resume past it even if a shallower sibling follows later in the same
    section - real notes are almost always uniformly nested, and a
    fragment with a gap in the middle would be more confusing than a
    clean, slightly shorter cutoff (used by read_fragment's
    include_children)."""
    if child_depth <= 0:
        for h in headings:
            if heading.line_start < h.line_start < heading.line_end:
                return h.line_start
        return heading.line_end
    limit_level = heading.level + child_depth
    for h in headings:
        if h.line_start <= heading.line_start or h.line_start >= heading.line_end:
            continue
        if h.level > limit_level:
            return h.line_start
    return heading.line_end


def own_text(raw_text: str, headings: List[Heading], heading: Heading) -> str:
    """This heading's text, stopping at its first child sub-heading."""
    return slice_lines(raw_text, heading.line_start, section_end_line(headings, heading, 0))


def text_with_children(raw_text: str, headings: List[Heading], heading: Heading, child_depth: int) -> str:
    """own_text, extended to include descendant subsections up to
    child_depth levels below `heading` (fragment-reader passport rule 3:
    include_children adds only child subsections up to a given depth)."""
    return slice_lines(raw_text, heading.line_start, section_end_line(headings, heading, child_depth))


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


# Splits on . ! ? followed by whitespace and an uppercase/Cyrillic capital
# letter (or end of text) - a heuristic, not a real sentence tokenizer: it
# will overcount an abbreviation like "т.е." and undercount an ellipsis.
# Good enough to flag "this doesn't look like exactly two sentences" for a
# human/Claude to double check, never to silently rewrite the text.
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[А-ЯЁA-Z])")


def count_sentences(text: str) -> int:
    text = text.strip()
    if not text:
        return 0
    parts = _SENTENCE_SPLIT_RE.split(text)
    return len([p for p in parts if p.strip()])


PARA_BREAK_RE = re.compile(r"^\s*$")


def split_paragraphs_with_bounds(lines: List[str], base_line: int = 1) -> List[tuple]:
    """Like split_paragraphs, but returns (line_start, line_end_exclusive,
    text) - 1-indexed against `base_line` (the file-numbering of lines[0]).
    Used by fragment addressing (a block id or line-range needs to know
    which whole paragraph it sits in, not just the paragraph's text)."""
    paras: List[tuple] = []
    buf: List[str] = []
    buf_start = None
    in_fence = False
    fence_marker = None
    in_callout = False

    def flush(end_idx: int):
        nonlocal buf_start
        if buf:
            joined = "\n".join(buf).strip("\n")
            if joined.strip():
                paras.append((base_line + buf_start, base_line + end_idx, joined))
            buf.clear()
        buf_start = None

    for i, line in enumerate(lines):
        stripped = line.strip()
        fm = FENCE_RE.match(stripped)
        if fm:
            marker = fm.group(1)[0] * 3
            if not in_fence:
                in_fence = True
                fence_marker = marker
                if buf_start is None:
                    buf_start = i
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
                flush(i)
            in_callout = True
            if buf_start is None:
                buf_start = i
            buf.append(line)
            continue
        in_callout = False
        if PARA_BREAK_RE.match(line):
            flush(i)
            continue
        if buf_start is None:
            buf_start = i
        buf.append(line)
    flush(len(lines))
    return paras


def split_paragraphs(text: str) -> List[str]:
    """Blank-line-delimited paragraphs, keeping fences/callouts atomic."""
    return [p[2] for p in split_paragraphs_with_bounds(text.splitlines())]


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
    lines = raw_text.splitlines()
    fenced = fence_mask(lines)
    for lineno, line in enumerate(lines, start=1):
        if fenced[lineno - 1]:
            continue
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
class Callout:
    type: str
    title: str
    text: str
    line_start: int
    line_end: int


@dataclass
class FragmentResult:
    status: str  # resolved | not_found | needs_context | out_of_scope
    path: str
    heading_path: Optional[list]
    line_start: Optional[int]
    line_end: Optional[int]
    text: Optional[str]
    content_hash: Optional[str]
    candidates: Optional[list] = None  # for needs_context: ambiguous headings/paragraph matches
    callouts: List[Callout] = field(default_factory=list)
    internal_refs_outside_range: List[str] = field(default_factory=list)
    truncated: bool = False


def extract_callouts(raw_text: str, line_start: int, line_end: int) -> List[Callout]:
    """Fragment-reader passport rule 6: a callout inside the range stays a
    separate semantic block rather than blending into the surrounding
    prose in `text` - callers that care about definitions/warnings/
    examples specifically can look at `callouts` instead of re-parsing."""
    lines = raw_text.splitlines()
    out: List[Callout] = []
    i = max(line_start - 1, 0)
    stop = min(line_end - 1, len(lines))
    while i < stop:
        m = CALLOUT_RE.match(lines[i])
        if not m:
            i += 1
            continue
        start = i
        body = [m.group(2)] if m.group(2) else []
        i += 1
        while i < stop and lines[i].strip().startswith(">"):
            body.append(re.sub(r"^>\s?", "", lines[i]))
            i += 1
        out.append(Callout(m.group(1), (m.group(2) or "").strip(), "\n".join(body).strip(), start + 1, i))
    return out


def _internal_refs_outside(raw_text: str, line_start: int, line_end: int) -> List[str]:
    """Fragment-reader passport rule 7, advisory half: a same-file heading/
    block link (`[[#Heading]]`, `[[#^id]]`) found *inside* the range. This
    module never auto-escalates status to `needs_context` over this - "is
    the meaning actually ambiguous without it" is the judgment call the
    passport leaves to the caller; it only surfaces the candidates."""
    refs = []
    for link in extract_wikilinks(slice_lines(raw_text, line_start, line_end)):
        if link.target == "" and link.anchor:
            refs.append(f"#{link.anchor}")
    return refs


def read_fragment(
    vault_path: Path,
    rel_path: str,
    heading_query: Optional[str] = None,
    block_id: Optional[str] = None,
    line_range: Optional[tuple] = None,
    include_children: bool = False,
    child_depth: int = 1,
    max_chars: Optional[int] = None,
) -> FragmentResult:
    """The addressed-reading primitive behind obsidian-fragment-reader
    (§3.15), reused directly by obsidian-research/-revise/-link/-moc/-hub
    rather than each re-implementing "read exactly this much". At most one
    of `block_id` / `line_range` / `heading_query` should normally be
    given; if more than one is passed, block_id wins, then line_range,
    then heading_query - all three omitted reads the whole file, as
    before.

    States (algorithms.md §2 "Состояния reader"): `resolved`, `not_found`,
    `needs_context` (ambiguous heading, or a block/paragraph match - not
    reachable for block_id/line_range, which are unambiguous by
    construction). `stale_address` does not apply: there is no cached
    RAPTOR address to go stale against, every call re-parses the live file
    fresh. `out_of_scope` is the caller's responsibility - this function
    has no opinion on vault scope excludes; check before calling if that
    matters (e.g. pathutil.is_excluded).
    """
    full_path = Path(vault_path) / rel_path
    if not full_path.is_file():
        return FragmentResult("not_found", rel_path, None, None, None, None, None)
    raw = read_text(full_path)
    parsed = parse_frontmatter(raw)
    headings = parse_headings(parsed.body, parsed.body_start_line)
    lines = raw.splitlines()
    total_lines = len(lines)

    def finish(status, h_path, ls, le, text, candidates=None):
        callouts, refs, truncated = [], [], False
        if status == "resolved" and ls is not None and le is not None:
            callouts = extract_callouts(raw, ls, le)
            refs = _internal_refs_outside(raw, ls, le)
            if max_chars and text is not None and len(text) > max_chars:
                text = text[:max_chars]
                truncated = True
        return FragmentResult(
            status, rel_path, h_path, ls, le, text,
            content_hash(text) if text is not None else None,
            candidates, callouts, refs, truncated,
        )

    def heading_path_for_line(line_no: int) -> Optional[list]:
        best = None
        for h in headings:
            if h.line_start <= line_no < h.line_end:
                best = h  # later (more specific/deeper) containing heading wins
        return list(best.path) if best else None

    if block_id:
        line_no = next(
            (i for i, line in enumerate(lines, start=1)
             if (m := BLOCK_ID_RE.search(line)) and m.group(1) == block_id),
            None,
        )
        if line_no is None:
            return finish("not_found", None, None, None, None)
        paras = split_paragraphs_with_bounds(lines, base_line=1)
        containing = next((p for p in paras if p[0] <= line_no < p[1]), None)
        ps, pe = containing[:2] if containing else (line_no, line_no + 1)
        return finish("resolved", heading_path_for_line(ps), ps, pe, slice_lines(raw, ps, pe))

    if line_range:
        ls, le = line_range
        le = min(le, total_lines + 1)
        if ls < 1 or ls > total_lines:
            return finish("not_found", None, None, None, None)
        return finish("resolved", heading_path_for_line(ls), ls, le, slice_lines(raw, ls, le))

    if heading_query is None:
        return finish("resolved", None, 1, total_lines + 1, raw)

    matches = find_heading(headings, heading_query)
    if not matches:
        return finish("not_found", None, None, None, None)
    if len(matches) > 1:
        return finish("needs_context", None, None, None, None,
                       candidates=[" > ".join(h.path) for h in matches])
    h = matches[0]
    depth = child_depth if include_children else 0
    end_line = section_end_line(headings, h, depth)
    return finish("resolved", list(h.path), h.line_start, end_line, slice_lines(raw, h.line_start, end_line))
