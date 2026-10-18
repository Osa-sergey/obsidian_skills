---
name: obsidian-fragment-reader
description: Read exactly one addressed piece of an Obsidian note — a section (optionally with its subsections), a single paragraph by its Obsidian block id (^abc123), or an explicit line range — instead of opening the whole file. Use this whenever you already have a path and a specific place in it (a heading, a `^blockid`, a line number) and want just that piece; when you need the two-sentence '## Суть' preview before deciding whether to read further; or when another skill's output (obsidian-search/-context) gave you a heading/anchor and now you need the actual text. Prefer a plain `Read` call only when you genuinely need the whole file.
---

# obsidian-fragment-reader

The addressed-reading primitive behind US-002/US-011: read the smallest
piece of a note that actually answers the question, with exact
provenance (path, heading path, line bounds, content hash) so what got
read is traceable. Full spec: `docs/spec/skills/15-obsidian-fragment-reader.md`;
runs from `~/.claude/skills/obsidian-fragment-reader/scripts/fragment_reader.py`.

## Three ways to address a fragment

```bash
# By heading (exact title, or 'Parent > Child' to disambiguate duplicates)
python3 ~/.claude/skills/obsidian-fragment-reader/scripts/fragment_reader.py read \
  --path "zettelkasten/notes/GraphRAG (Microsoft).md" --heading "Краткое описание"

# The same heading plus one level of subsections
python3 ~/.claude/skills/obsidian-fragment-reader/scripts/fragment_reader.py read \
  --path "notes/Статья.md" --heading "Механизм" --include-children --child-depth 1

# By Obsidian block id (a paragraph tagged "...text ^abc123")
python3 ~/.claude/skills/obsidian-fragment-reader/scripts/fragment_reader.py read \
  --path "notes/Статья.md" --block-id abc123

# By explicit line range (1-indexed, both ends inclusive)
python3 ~/.claude/skills/obsidian-fragment-reader/scripts/fragment_reader.py read \
  --path "notes/Статья.md" --line-range 42-58
```

Give exactly one of `--heading` / `--block-id` / `--line-range`. A bare
`--heading` title matches by exact text; if more than one heading in the
file shares that text, the result comes back `needs_context` with every
candidate as a `Parent > Child` path - re-run with that exact chain rather
than guessing which one you meant.

**`--include-children` stays off by default on purpose** (rule 4: "не
добавлять соседние разделы «для контекста» без причины"). Turn it on only
when the subsections are actually needed - it stops at the first
descendant deeper than `--child-depth`, so it will not silently pull in a
whole multi-level subtree.

## The `## Суть` shortcut

```bash
python3 ~/.claude/skills/obsidian-fragment-reader/scripts/fragment_reader.py preview --path "notes/Статья.md"
```

Cheapest possible read before deciding whether a note is worth opening
further - REQ-KNO-0001's two-sentence gist. **A missing `## Суть` reports
`status: "no_suti"`, not an error** - most existing notes predate that
convention; fall back to the note's YAML `summary` or just read a section
addressed the normal way.

## Reading the result

- `heading_path`: the full ancestor chain (`["Механизм", "Подраздел А"]`),
  not just the immediate heading - use it to understand where the
  fragment actually sits, and to build a `Parent > Child` re-query if you
  need to disambiguate later.
- `callouts`: any `> [!type]` blocks inside the range, extracted
  separately with their type/title/text - a definition or warning callout
  is worth surfacing on its own rather than leaving it flattened into
  `text`.
- `internal_refs_outside_range`: same-file links (`[[#Other Heading]]`,
  `[[#^blockid]]`) found inside the fragment that point *outside* the
  returned range. This is advisory only - the script does not decide
  whether the fragment's meaning is actually unclear without them (rule
  7 leaves that judgment to you); if a fragment references something and
  doesn't make sense on its own, read that target too before using it as
  evidence, rather than guessing at what it says.
- `content_hash`: identifies exactly this text as read right now. If you
  later want to *change* this same region, `obsidian-revise`/
  `obsidian-link`/`obsidian-metadata` compute and check their own fresh
  hash at write time - this one is for your own bookkeeping, not
  something to feed back into a patch.
- Status `not_found` (bad path, or no heading/block id matching) and
  `needs_context` (ambiguous heading) are both plain, expected outcomes,
  not crashes - handle them the same way you'd handle any other
  "didn't resolve" result.

## What this skill does not do

- It never expands to a whole article "just in case" - every read is
  exactly the address you gave, plus children only when you explicitly
  ask.
- It has no opinion on whether a path is inside the vault's allowed scope
  - check that first if it matters (or use a skill that already does,
  like `obsidian-search`, which never surfaces an out-of-scope path in
  the first place).
- It doesn't resolve a RAPTOR node address - skill 13/18 (semantic
  search / index) aren't built in this project yet, so there is no vector
  index to resolve against. Every read here re-parses the live Markdown,
  which is also why there's no `stale_address` state: an address is never
  cached, so it can't go stale.
