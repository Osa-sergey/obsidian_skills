---
name: obsidian-retrieve
description: Get a minimally-sufficient, ranked set of candidate notes for a task by combining keyword search (Omnisearch), RAPTOR semantic search, and MOC/graph proximity into one deduplicated result with a token budget. Use this instead of calling obsidian-search and obsidian-semantic-search separately whenever the task needs *both* precision and recall — before obsidian-research does synthesis, before obsidian-qa answers a narrow question, or whenever the user's request is broad enough that a single retriever would likely miss something ("собери всё что у меня есть про X", "что я знаю о Y перед тем как писать статью"). For a quick, single-mechanism lookup (exact filename, exact phrase) use obsidian-search directly instead — this skill's overhead (multiple retrievers, budget accounting) isn't worth it for that.
---

# obsidian-retrieve

Runs Omnisearch and semantic search against the same query set, folds
graph/MOC neighbors in for `deep` mode, deduplicates by file, and ranks by
a combined score — then tells you what fits in the mode's token budget and
what got cut. Full spec: `docs/spec/skills/14-obsidian-retrieve.md`
(US-002/US-011); the orchestration logic lives in
`lib/obsidian_common/retrieve.py`. Runs from
`~/.claude/skills/obsidian-retrieve/scripts/retrieve.py`.

**Honest scope note**: this does not yet do a Dataview/Bases pre-filter
(spec mentions it; skills 11/12 that would back it aren't built) — check
`retrievers_used` in the output rather than assuming every mechanism the
spec describes actually ran.

## Before the first call

Same vault connection as every other skill (`bin/obsidian-vault`
register/connect). Omnisearch and semantic search degrade independently —
either can be missing without blocking the other (see
`retrievers_skipped` in the output) — but the more of them are actually
running, the better the result, so check `obsidian-index-sync status` for
the files you care about if semantic results look thin.

## Search

```bash
python3 ~/.claude/skills/obsidian-retrieve/scripts/retrieve.py search \
  --query "GraphRAG граф знаний" --mode narrow

# multiple phrasings of the same need - each is run against both
# retrievers and merged, same idea as obsidian-search's multi --query
python3 ~/.claude/skills/obsidian-retrieve/scripts/retrieve.py search \
  --query "чанкинг для RAG" "chunking strategies" --mode deep
```

**`narrow`** (default): high precision, small budget
(`limits.narrow.max_notes`/`max_tokens` from the vault profile), no graph
expansion — use for a specific, bounded question.

**`deep`**: wider recall, graph/MOC neighbor expansion from the top
candidates already found (backlinks + outlinks, `limits.deep.graph_depth`
hops), bigger budget — use before a synthesis/research task that needs to
find what it doesn't already know to ask for.

## Reading the result

Each candidate reports `combined_score` (0.5×normalized-omnisearch +
0.5×normalized-semantic + a small graph-proximity bonus — normalized
*within this run*, not a fixed global scale, since Omnisearch and cosine
scores aren't comparable numbers), `reasons` (which retriever(s) found it),
and — when semantic search found a specific node inside the file — a
`semantic_match` with the exact `heading_path`/line range to read, not
just "this file might be relevant." A candidate with only `omnisearch` in
`reasons` has no addressed node; read it via `obsidian-search`'s excerpt
or fall back to reading the file's own structure.

`budget_used_tokens`/`budget_max_tokens`/`budget_truncated` tell you
whether everything relevant actually fit — if truncated, the
`recommendations` list says how many candidates were cut and suggests
`mode=deep` for a wider pass rather than silently dropping them from
consideration.

**Never present a `semantic_match`'s `preview` as the actual evidence** —
it may be an LLM-generated summary (`summary_source: llm`) or a crude
extractive stand-in (`extractive_fallback`); either way it's a pointer.
Read the real fragment with `obsidian-fragment-reader` using the reported
path and line range before quoting or citing anything.

### Related

[§3.1 obsidian-search](../obsidian-search/SKILL.md) for a single-mechanism
lookup. [§3.13 obsidian-semantic-search](../obsidian-semantic-search/SKILL.md)
is one of the two retrievers this orchestrates, callable on its own too.
[§3.15 obsidian-fragment-reader](../obsidian-fragment-reader/SKILL.md) for
actually reading what a candidate points to.
