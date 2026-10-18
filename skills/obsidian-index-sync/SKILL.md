---
name: obsidian-index-sync
description: Keep the RAPTOR/Qdrant semantic index in sync with a connected Obsidian vault's real files after any write. Use this at the end of every successfully applied vault change (new note, edit, delete, rename) via obsidian-author/revise/link/metadata/moc/hub/query-builder or a direct file edit — never claim a write is "done" without running this after it, and never claim search results are current if it was skipped or failed. Also use it directly when the user wants to rebuild the semantic index for specific articles by name ("обнови индекс для статьи X", "переиндексируй Y и Z"), for a full vault rebuild, or to check whether a given file is currently indexed at all. Trigger on "sync the index", "reindex", "update embeddings", "rebuild semantic search", or any mention of the index being stale/dirty/out of date.
---

# obsidian-index-sync

Full replacement of one changed file's vectors, never an in-place diff of
individual nodes (ADR-0006) — every call deletes a path's old vectors
first, then rebuilds its whole RAPTOR tree (article → section →
subsection → chunk/callout) and writes fresh ones. Full spec:
`docs/spec/skills/18-obsidian-index-sync.md` (US-014); the actual
chunk → summarize → embed → store pipeline lives in
`lib/obsidian_common/{raptor,summarizer,embeddings,vectorstore,indexing}.py`
if you need the details — this file only covers how to call it. Runs from
`~/.claude/skills/obsidian-index-sync/scripts/sync.py`.

**This skill is a mandatory step, not an optional convenience.** CLAUDE.md
invariant 6: after any real vault write, finish with this skill — delete
old vectors of changed files, rebuild their RAPTOR hierarchy fully, clear
vectors for deleted files. On failure, report `index_dirty`, not "search
is current."

## Before the first call

Needs a connected vault (see `obsidian-search`'s SKILL.md for the same
`bin/obsidian-vault register`/`connect` setup) **and** three running
external services — see this project's `README.md` § "Semantic search
setup" for the full quickstart:

1. **Qdrant** (Docker container or embedded local mode) — required. Without
   it every call returns `index_dirty`.
2. **LM Studio embeddings model** (`qwen3-embedding-0.6b-mlx` by default)
   — required. Without it every call returns `index_dirty` (old vectors
   for the file are deleted first, so a failed resync briefly leaves that
   file with *zero* indexed vectors, not stale ones — report this plainly
   if it happens, don't retry silently in a loop).
3. **LM Studio summarizer model** (`gpt-oss-20b-...` by default) —
   optional. If disabled or unreachable, section/subsection/article nodes
   get an extractive stand-in (title + first chunk) instead of a real
   generated summary, tagged `summary_source: extractive_fallback` in
   their payload — the file still gets indexed, just with lower-quality
   summary-level vectors. Report how many nodes fell back when it's
   non-zero; don't silently treat it as a full success.

Check what's actually running before promising a clean result:

```bash
python3 ~/.claude/skills/obsidian-index-sync/scripts/sync.py status --paths "some/note.md"
```

A `0 vectors ⚠️ not indexed` result for a file you expect to be indexed is
informative, not necessarily an error — it may just never have been synced
yet.

## After a write — resync the changed files

The normal, mandatory call, once per finished write batch (not once per
individual edit inside it):

```bash
python3 ~/.claude/skills/obsidian-index-sync/scripts/sync.py resync \
  --paths "PARA/projects/Note A.md" "zettelkasten/notes/Note B.md"

python3 ~/.claude/skills/obsidian-index-sync/scripts/sync.py delete \
  --paths "zettelkasten/notes/Removed Note.md"

python3 ~/.claude/skills/obsidian-index-sync/scripts/sync.py rename \
  --old "zettelkasten/notes/Old Name.md" --new "zettelkasten/notes/New Name.md"
```

Multiple `--paths` in one call is fine and preferred over one call per
file — output is one record per file either way, so nothing about
per-file error handling is lost by batching.

## Resync by article name, not path

The direct-invocation case: rebuild the index for a specific set of
articles by name without knowing or typing their exact vault paths.
Resolves each name against the filename, YAML `title`, and `aliases`
(same normalization as `obsidian-search`) — **never a fuzzy/substring
guess**, an ambiguous or unresolved name is reported as `not_indexable`
with the reason, never silently skipped or silently resolved to the
"closest" match:

```bash
python3 ~/.claude/skills/obsidian-index-sync/scripts/sync.py resync-titles \
  --titles "GraphRAG (Microsoft)" "Late Chunking" "Proposition Indexing"
```

If a name doesn't resolve, fix the name (or use `resync --paths` with the
exact path once you have it from `obsidian-search`) rather than retrying
the same ambiguous name expecting a different result.

## Full vault rebuild

```bash
python3 ~/.claude/skills/obsidian-index-sync/scripts/sync.py full
```

Walks every `.md` file in scope and resyncs it. **This is expensive** —
one embedding call (and, if the summarizer is enabled, several chat
completions per section) per file, for every file in the vault. Warn the
user before running it on a large vault and prefer `resync`/`resync-titles`
for anything narrower than "the whole thing changed" (a migration, a first
build, a model change forcing a full reindex per ADR-0009). `.canvas`/
`.base` files are skipped — not yet implemented, reported as a count in
the output, not silently dropped.

## Reading the result

Every subcommand prints one line per file: `status  path  (details)`.
`status` is one of `indexed | deleted | not_indexable | index_dirty` —
never invent a different word for it when reporting to the user. Add
`--format json` for a machine-readable `{results: [...], index_dirty:
bool}` payload when this is being called as part of a larger automated
write flow rather than read directly.

**Never tell the user "search is up to date" if any result came back
`index_dirty`** — say plainly that indexing failed for those files, what
the error was, and that semantic search results for them may be
incomplete or missing until a retry succeeds.
