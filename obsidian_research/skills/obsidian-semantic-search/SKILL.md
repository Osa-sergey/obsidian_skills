---
name: obsidian-semantic-search
description: Search a connected Obsidian vault by meaning, not keyword, across every level of a note's structure (whole article, section, subsection, or individual chunk) using the RAPTOR index obsidian-index-sync builds. Use this when a keyword/Omnisearch search (obsidian-search) misses because the user's phrasing doesn't match the vault's wording, when the user asks a conceptual question ("что у меня есть про X-подобные подходы", "заметки в духе Y") rather than naming an exact term, or when obsidian-retrieve needs a RAPTOR retriever internally. Do not use this as a replacement for obsidian-search's exact filename/title/text lookups — the two are complementary, not competing. Requires the index to actually be built for the vault (obsidian-index-sync must have run) and LM Studio's embeddings model to be reachable, or every call reports embeddings_unavailable rather than empty/wrong results.
---

# obsidian-semantic-search

Embeds a query and finds the nearest RAPTOR nodes by cosine similarity —
articles, sections, subsections, chunks and callouts all live in the same
index, so a match can be a whole article's summary or one paragraph,
depending on what's actually closest. Full spec:
`docs/spec/skills/13-obsidian-semantic-search.md` (US-011); the vector
math lives in `lib/obsidian_common/semantic.py` if you need the details.
Runs from `~/.claude/skills/obsidian-semantic-search/scripts/semantic_search.py`.

**This skill never returns article text, only a pointer to it** (path +
line range + heading path + a short preview). A returned `preview` may be
a real LLM-generated summary or a crude extractive stand-in
(`summary_source` tells you which) — either way, **never present it as the
answer or as evidence**. Read the actual text with
`obsidian-fragment-reader` using the match's `source_path`/line range
before quoting or relying on anything it says (foundation.md: "исходный
Markdown — источник истины", generated summaries are not proof).

## Before the first call

Same vault connection as every other skill here (`bin/obsidian-vault`
register/connect — see `obsidian-search`'s SKILL.md). Additionally needs
the RAPTOR index actually built: if `obsidian-index-sync status` reports
`0 vectors` for files you expect results from, run `obsidian-index-sync`
first (either `resync`/`resync-titles` for specific files, or `full` for
the whole vault) — this skill only reads an existing index, it never
builds one.

## Search

```bash
python3 ~/.claude/skills/obsidian-semantic-search/scripts/semantic_search.py search \
  --query "графовая структура знаний и community summaries" --top-k 10

# narrow to specific tree levels (default: search across all of them)
python3 ~/.claude/skills/obsidian-semantic-search/scripts/semantic_search.py search \
  --query "..." --node-levels section subsection

# search the "raw" (unsummarized, verbatim) vector space instead of
# "summary" - only section/subsection/article nodes small enough to have
# gotten a raw vector (see raptor.should_embed_raw) show up here; useful
# when the query names exact terms/wording that an LLM summary may have
# paraphrased away
python3 ~/.claude/skills/obsidian-semantic-search/scripts/semantic_search.py search \
  --query "..." --using raw
```

Each match reports `score`, `node_level`, `heading_path`, `source_path`,
the line range, a `preview`, and `parent_id`/`child_ids` for the next step.
`summary_source` on a section/subsection/article match tells you whether
its "summary" vector came from a real LLM summary (`llm`) or the
extractive fallback (`extractive_fallback`, i.e. no summarizer model was
available when it was indexed) — treat a fallback match's preview as
cruder and lean more on actually reading the fragment.

## Progressive disclosure — expand a promising match

A high-scoring `section`/`subsection`/`article` match is often a starting
point, not the answer — expand its children to see the actual chunks
underneath, or its parent to see the surrounding context:

```bash
python3 ~/.claude/skills/obsidian-semantic-search/scripts/semantic_search.py expand \
  --node-ids <child_id_1> <child_id_2>
```

`expand` does a direct ID lookup, not a new similarity search — every
result has `score=1.0` (meaningless here, don't sort by it) and
`vector_used=none`. Use it to walk `child_ids` down into a section, or
`parent_id` up to a section from one of its chunks.

## Degraded results — never silently pass them off as complete

If the embeddings server is unreachable, the CLI reports
`embeddings_unavailable` and returns no matches — **say this plainly to
the user** ("semantic search is currently unavailable, here's what
keyword search found instead" via `obsidian-search`), don't just report
"no results" as if that were a real negative finding. Same for
`vectorstore_unavailable` (Qdrant down). There is currently no persisted
"this file is index_dirty" flag to check ahead of time — a file that
failed to index simply has no vectors and won't appear in results at all,
which is honest (nothing stale is returned) but means a suspiciously thin
result set for a topic you know the vault covers is worth checking against
`obsidian-index-sync status` before concluding "the vault doesn't have
this."

### Related

[§3.14 obsidian-retrieve](../obsidian-retrieve/SKILL.md) usually calls this
as one of several retrievers, not on its own. [§3.15
obsidian-fragment-reader](../obsidian-fragment-reader/SKILL.md) for
actually reading what a match points to. [§3.18
obsidian-index-sync](../obsidian-index-sync/SKILL.md) builds what this
skill reads.
