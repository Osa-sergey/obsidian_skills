"""RAPTOR-style hierarchical chunking of a Markdown note.

foundation.md §2.6: `article -> section -> subsection -> paragraph
group -> atomic paragraph/chunk`, heading boundaries take priority over
blind token chunking (defaults.md §11 "Unit"), a callout stays its own
leaf with its parent heading preserved. This module builds that node tree
from the *live* Markdown (reusing markdown.py's heading/paragraph parsing
- the same source of truth every other skill reads), for
obsidian-index-sync to embed and store and obsidian-semantic-search to
query.

This module builds the tree and a crude extractive stand-in for every
section/subsection/article node's `text` (title + first child's text) but
does no network I/O itself - `fill_summaries()` (also in this module)
overwrites that stand-in with a real LLM-generated summary of *all* of a
node's descendants, given a caller-supplied summarizer callable; nodes
where the summarizer wasn't called (feature disabled) or failed keep the
extractive stand-in, tagged via `summary_source` so nothing downstream
mistakes one for the other.

`raw_text_for_node()` is the second piece obsidian-index-sync needs: the
verbatim, unsummarized text of a node's whole subtree (own text is already
the leaf chunks in tree order, no reconstruction beyond concatenation) -
used for an optional second ("raw") embedding vector alongside the summary
vector, when that subtree is small enough that embedding it whole is still
a useful, focused representation rather than a diluted one.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from . import markdown as md

# defaults.md §11 "Unit": leaf target 150-350 tokens, hard max ~500,
# forced split at a sentence boundary only when one paragraph alone
# exceeds the hard max. CHARS_PER_TOKEN is the same rough, language-mixed
# heuristic used in obsidian-qa's budget tally - not a real tokenizer.
CHARS_PER_TOKEN = 4
LEAF_TARGET_MIN_TOKENS = 150
LEAF_TARGET_MAX_TOKENS = 350
LEAF_HARD_MAX_TOKENS = 500
PREVIEW_CHARS = 220

# A section/subsection/article's raw (unsummarized) subtree text still gets
# its own embedding vector when it's under this size - past it the raw text
# is judged too diluted to be a useful single vector, so only the LLM
# summary vector is stored for that node (user decision, 2026-09-29).
RAW_VECTOR_MAX_TOKENS = 3500


def _tokens(text: str) -> int:
    return max(1, len(text) // CHARS_PER_TOKEN)


def _preview(text: str) -> str:
    text = text.strip()
    if len(text) <= PREVIEW_CHARS:
        return text
    cut = text.rfind(" ", 0, PREVIEW_CHARS)
    cut = cut if cut > 0 else PREVIEW_CHARS
    return text[:cut].rstrip() + "…"


def _stable_id(vault_id: str, source_path: str, kind: str, heading_path: tuple, index: int) -> str:
    # `kind` keeps heading/article node IDs in a disjoint seed space from
    # chunk/callout leaf IDs - without it, a heading node (always index 0
    # within its own heading_path) collides with the first leaf under it
    # whenever that leaf also lands on index 0 (e.g. the very first
    # heading in a file with no lead paragraph before it), silently
    # merging two different nodes into one Qdrant point.
    seed = f"{vault_id}|{source_path}|{kind}|{'/'.join(heading_path)}|{index}"
    digest = hashlib.md5(seed.encode("utf-8")).digest()
    return str(uuid.UUID(bytes=digest))


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


def _force_split_paragraph(text: str, max_tokens: int) -> List[str]:
    """Only reached when a single paragraph alone exceeds the hard max -
    split at sentence boundaries, one sentence minimum per piece (never
    mid-sentence), grouping sentences up to max_tokens per piece."""
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(text) if s.strip()]
    if len(sentences) <= 1:
        return [text]
    pieces, buf = [], []
    buf_tokens = 0
    for s in sentences:
        t = _tokens(s)
        if buf and buf_tokens + t > max_tokens:
            pieces.append(" ".join(buf))
            buf, buf_tokens = [], 0
        buf.append(s)
        buf_tokens += t
    if buf:
        pieces.append(" ".join(buf))
    return pieces


@dataclass
class RaptorNode:
    node_id: str
    vault_id: str
    source_path: str
    node_level: str  # article | section | subsection | chunk | callout
    heading_path: List[str]
    parent_id: Optional[str]
    child_ids: List[str] = field(default_factory=list)
    line_start: int = 0
    line_end: int = 0
    content_hash: str = ""
    text: str = ""
    preview: str = ""
    callout_type: Optional[str] = None
    # "raw" - a chunk/callout leaf, its own text is never a summary of
    #         anything else.
    # "llm" - an article/section/subsection node whose `text` is a real
    #         generated summary from fill_summaries().
    # "extractive_fallback" - same node levels, but `text` is still the
    #         title+first-child stand-in because fill_summaries() was
    #         never run or failed for this node - never claim this is an
    #         LLM summary downstream.
    summary_source: str = "raw"

    def to_payload(self) -> dict:
        """Qdrant point payload - REQ-RET-0002's required fields
        (source/source_path/vault_id/node_id/node_level/heading_path/
        content_hash/range) plus this module's own tree-linkage fields."""
        return {
            "source": self.source_path.rsplit("/", 1)[-1],
            "source_path": self.source_path,
            "vault_id": self.vault_id,
            "summary_source": self.summary_source,
            "node_id": self.node_id,
            "node_level": self.node_level,
            "heading_path": self.heading_path,
            "parent_id": self.parent_id,
            "child_ids": self.child_ids,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "content_hash": self.content_hash,
            "preview": self.preview,
            "callout_type": self.callout_type,
        }


def _heading_level_name(depth: int) -> str:
    return "section" if depth == 1 else "subsection"


def _chunk_own_text(
    raw: str, vault_id: str, source_path: str, heading_path: tuple,
    line_start: int, line_end: int, parent_id: str, start_index: int,
) -> List[RaptorNode]:
    """Splits one heading's own text (or the article root's pre-heading
    text) into chunk/callout leaves, grouped to the target token range and
    never crossing a paragraph boundary except when force-splitting an
    oversized single paragraph."""
    lines = raw.splitlines()
    own_lines = lines[line_start - 1: line_end - 1]
    if not any(l.strip() for l in own_lines):
        return []
    paras = md.split_paragraphs_with_bounds(own_lines, base_line=line_start)

    nodes: List[RaptorNode] = []
    buf_text: List[str] = []
    buf_start: Optional[int] = None
    buf_end: Optional[int] = None
    buf_tokens = 0
    idx = start_index

    def flush():
        nonlocal buf_text, buf_start, buf_end, buf_tokens, idx
        if not buf_text:
            return
        text = "\n\n".join(buf_text)
        nodes.append(RaptorNode(
            node_id=_stable_id(vault_id, source_path, "chunk", heading_path, idx),
            vault_id=vault_id, source_path=source_path, node_level="chunk",
            heading_path=list(heading_path), parent_id=parent_id,
            line_start=buf_start, line_end=buf_end,
            content_hash=md.content_hash(text), text=text, preview=_preview(text),
        ))
        idx += 1
        buf_text, buf_start, buf_end, buf_tokens = [], None, None, 0

    for p_start, p_end, p_text in paras:
        is_callout = bool(md.CALLOUT_RE.match(p_text.strip().splitlines()[0]) if p_text.strip() else False)
        if is_callout:
            flush()
            m = md.CALLOUT_RE.match(p_text.strip().splitlines()[0])
            nodes.append(RaptorNode(
                node_id=_stable_id(vault_id, source_path, "callout", heading_path, idx),
                vault_id=vault_id, source_path=source_path, node_level="callout",
                heading_path=list(heading_path), parent_id=parent_id,
                line_start=p_start, line_end=p_end,
                content_hash=md.content_hash(p_text), text=p_text, preview=_preview(p_text),
                callout_type=m.group(1) if m else None,
            ))
            idx += 1
            continue

        p_tokens = _tokens(p_text)
        if p_tokens > LEAF_HARD_MAX_TOKENS:
            flush()
            for piece in _force_split_paragraph(p_text, LEAF_TARGET_MAX_TOKENS):
                nodes.append(RaptorNode(
                    node_id=_stable_id(vault_id, source_path, "chunk", heading_path, idx),
                    vault_id=vault_id, source_path=source_path, node_level="chunk",
                    heading_path=list(heading_path), parent_id=parent_id,
                    line_start=p_start, line_end=p_end,
                    content_hash=md.content_hash(piece), text=piece, preview=_preview(piece),
                ))
                idx += 1
            continue

        if buf_tokens and buf_tokens + p_tokens > LEAF_TARGET_MAX_TOKENS:
            flush()
        buf_text.append(p_text)
        buf_start = p_start if buf_start is None else buf_start
        buf_end = p_end
        buf_tokens += p_tokens
        if buf_tokens >= LEAF_TARGET_MIN_TOKENS:
            flush()
    flush()
    return nodes


def build_raptor_tree(raw_text: str, vault_id: str, source_path: str) -> List[RaptorNode]:
    """Returns a flat list of every node for this file - the article root
    first, then one node per heading (section/subsection, by relative
    depth from the first heading actually used - a file need not start at
    H1), then that heading's own chunk/callout leaves, in document order.
    `parent_id`/`child_ids` encode the tree; callers needing just the
    leaves can filter node_level in {"chunk", "callout"}.
    """
    parsed = md.parse_frontmatter(raw_text)
    headings = md.parse_headings(parsed.body, parsed.body_start_line)
    total_lines = len(raw_text.splitlines()) + 1

    article_id = _stable_id(vault_id, source_path, "article", (), 0)
    # Extractive stand-in for an article-level summary (see module
    # docstring): the "Суть"/summary section if present, else falls back
    # to filled in below once the file's lead/first-section text is known.
    # This is what index-sync embeds for the article node - without *some*
    # text here the article point would embed empty content and never
    # surface as a search hit.
    article_summary = md.extract_summary_suti(raw_text, headings) or parsed.meta.get("summary") or ""
    article = RaptorNode(
        node_id=article_id, vault_id=vault_id, source_path=source_path,
        node_level="article", heading_path=[], parent_id=None,
        line_start=1, line_end=total_lines,
        content_hash=md.content_hash(raw_text),
        text=article_summary, preview=_preview(article_summary),
        summary_source="extractive_fallback",
    )
    nodes: List[RaptorNode] = [article]

    # text before the first heading (e.g. an un-headed lead paragraph)
    # belongs to the article root itself.
    pre_heading_end = headings[0].line_start if headings else total_lines
    lead_nodes = _chunk_own_text(raw_text, vault_id, source_path, (), parsed.body_start_line,
                                  pre_heading_end, article_id, 0)
    for n in lead_nodes:
        article.child_ids.append(n.node_id)
    nodes.extend(lead_nodes)
    next_index = len(lead_nodes)

    id_by_heading_path: dict = {(): article_id}
    for h in headings:
        # depth relative to this file's *first* heading level, not the
        # absolute Markdown level - a file starting at H2 still gets
        # node_level "section" for its top tier (own_text/section_end_line
        # elsewhere in this package make the same "no H1 required"
        # allowance).
        min_level = headings[0].level
        rel_depth = h.level - min_level + 1
        level_name = _heading_level_name(1) if rel_depth == 1 else _heading_level_name(2)

        parent_path = h.path[:-1]
        parent_id = id_by_heading_path.get(parent_path, article_id)
        heading_node_id = _stable_id(vault_id, source_path, "heading", h.path, 0)
        heading_node = RaptorNode(
            node_id=heading_node_id, vault_id=vault_id, source_path=source_path,
            node_level=level_name, heading_path=list(h.path), parent_id=parent_id,
            line_start=h.line_start, line_end=h.line_end,
            content_hash=md.content_hash(md.own_text(raw_text, headings, h)),
            text="", preview="",
            summary_source="extractive_fallback",
        )
        nodes.append(heading_node)
        id_by_heading_path[h.path] = heading_node_id
        if parent_id == article_id:
            article.child_ids.append(heading_node_id)
        else:
            for n in nodes:
                if n.node_id == parent_id:
                    n.child_ids.append(heading_node_id)
                    break

        own_end = md.section_end_line(headings, h, child_depth=0)
        leaves = _chunk_own_text(raw_text, vault_id, source_path, h.path,
                                  h.line_start + 1, own_end, heading_node_id, next_index)
        heading_node.child_ids.extend(n.node_id for n in leaves)
        nodes.extend(leaves)
        next_index += len(leaves)
        # Extractive stand-in for a section summary: heading title plus
        # its first leaf's text. Without this the heading node would embed
        # as empty text and never surface as a search hit at section
        # granularity - see module docstring on why this isn't a real
        # generated summary.
        heading_node.text = (h.path[-1] + "\n\n" + leaves[0].text) if leaves else h.path[-1]
        heading_node.preview = _preview(heading_node.text)

    return nodes


def _postorder_summarize(
    node_id: str, nodes_by_id: Dict[str, "RaptorNode"],
    summarize_fn: Callable[[List[str]], str], errors: Dict[str, str],
) -> None:
    node = nodes_by_id[node_id]
    if node.node_level not in ("article", "section", "subsection"):
        return  # chunk/callout leaves keep their own text - nothing to summarize
    for child_id in node.child_ids:
        _postorder_summarize(child_id, nodes_by_id, summarize_fn, errors)
    # By now every child that needed summarizing already has its final
    # text (its own if a leaf, its generated summary if a heading) - this
    # is exactly what makes the recursion bottom-up rather than flat.
    child_texts = [nodes_by_id[cid].text for cid in node.child_ids if nodes_by_id[cid].text.strip()]
    if not child_texts:
        return  # nothing to summarize; extractive fallback (likely also empty) stands
    try:
        summary = summarize_fn(child_texts)
    except Exception as exc:  # noqa: BLE001 - any summarizer failure degrades, never propagates
        errors[node_id] = str(exc)
        return
    if summary and summary.strip():
        node.text = summary.strip()
        node.preview = _preview(node.text)
        node.summary_source = "llm"
    else:
        errors[node_id] = "summarizer returned empty text"


def fill_summaries(nodes: List["RaptorNode"], summarize_fn: Callable[[List[str]], str]) -> Dict[str, str]:
    """Replaces every article/section/subsection node's extractive
    stand-in `text` with a real LLM-generated summary of *all* of its
    direct children (not just the first, unlike the stand-in) - bottom-up,
    so a section's summary is built from its subsections' own summaries
    plus its own chunk text, not by re-reading raw text at every level.

    `summarize_fn(texts) -> str` is caller-supplied (obsidian_common.
    summarizer.LLMSummarizer.summarize_token_aware, normally) so this
    module keeps doing no network I/O itself. A node whose summarize_fn
    call raises or returns empty text keeps its extractive stand-in and
    `summary_source` stays "extractive_fallback" - this never raises out
    of the whole tree for one bad node, matching CLAUDE.md invariant 6
    (never claim a degraded result is a complete one). Returns
    {node_id: error message} for every node that fell back, so the caller
    can report e.g. "3 of 12 sections used the extractive fallback"
    instead of silently hiding it.
    """
    nodes_by_id = {n.node_id: n for n in nodes}
    roots = [n for n in nodes if n.parent_id is None]
    errors: Dict[str, str] = {}
    for root in roots:
        _postorder_summarize(root.node_id, nodes_by_id, summarize_fn, errors)
    return errors


def raw_text_for_node(node_id: str, nodes_by_id: Dict[str, "RaptorNode"]) -> str:
    """Verbatim concatenation of every leaf's text under this node, in
    document order, WITH the node's own heading title (and every nested
    subsection's title, recursively) interleaved in place - the
    article/section/subsection's full, unsummarized subtree text as a
    reader would actually see it, not just the bare paragraph bodies with
    the structure stripped out. Without the titles, a raw vector for e.g.
    a section full of short generically-worded subsections would carry no
    signal from the one thing that actually distinguishes them - their
    heading text. A chunk/callout leaf's own text already *is* this (it
    has no title of its own), so the recursion bottoms out there
    directly."""
    node = nodes_by_id[node_id]
    if node.node_level in ("chunk", "callout"):
        return node.text
    parts = [node.heading_path[-1]] if node.heading_path else []
    parts.extend(raw_text_for_node(cid, nodes_by_id) for cid in node.child_ids)
    return "\n\n".join(p for p in parts if p.strip())


def should_embed_raw(raw_text: str) -> bool:
    """Whether a section/subsection/article's raw subtree text is still
    small enough to be worth its own embedding vector alongside the
    summary vector - past RAW_VECTOR_MAX_TOKENS the text is judged too
    diluted a single vector to be a useful match target (user decision,
    2026-09-29: ~3500 tokens, matching the old pipeline's article-summary
    overflow threshold)."""
    return _tokens(raw_text) <= RAW_VECTOR_MAX_TOKENS
