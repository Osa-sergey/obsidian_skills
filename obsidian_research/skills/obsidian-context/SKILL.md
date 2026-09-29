---
name: obsidian-context
description: Collect the graph context around one or more Obsidian notes — outgoing links, backlinks, or both, out to a set depth — with the exact path/reason each note was reached by. Use this whenever the user wants to explore what's "around", "linked to", "connected to", or "related to" a note; wants the neighborhood/environment of a topic before reading into it; asks what links to a note or what a note links out to; or wants a bounded set of source candidates for research (pair it with obsidian-research). Also use it before proposing new cross-links, since it's the only way to see what's already connected vs. not. Needs paths from obsidian-search (or an exact/likely note title) as its starting point, and the same connected-vault setup obsidian-search uses.
---

# obsidian-context

Answers "what's around this note" as a graph-discovery problem: it walks
real wikilinks/embeds/frontmatter-links outward from one or more starting
notes and returns addresses, levels, and the exact edge each node was
reached through. It does **not** read note bodies (beyond an optional cheap
preview, clearly marked as such) and it does **not** judge which neighbor
actually matters — that reading and that judgment happen afterward, with
`Read`/`obsidian-research`, using the paths this returns. Full spec:
`docs/spec/skills/02-obsidian-context.md` (US-002); defaults `C1–C6` in
`docs/spec/defaults.md` (both relative to this project's root, the
`obsidian_research/` folder).

This skill runs from `~/.claude/skills/obsidian-context/scripts/context.py`
regardless of which project you're currently in — use that path directly,
not one relative to the current working directory.

## Depth means graph hops, not folders or headings

Level 0 is the start note(s) themselves; level 1 is their direct neighbors;
level 2 is two hops away. If the user asks for "depth 2", that's what they
mean — it is unrelated to how deep a heading is nested or how many folders
a path has.

## Running it

Start from a path `obsidian-search` gave you, or a note title if you're
reasonably sure it's unique:

```bash
python3 ~/.claude/skills/obsidian-context/scripts/context.py --start "zettelkasten/notes/GraphRAG (Microsoft).md" --mode deep --direction both
python3 ~/.claude/skills/obsidian-context/scripts/context.py --start "Заметка A,Заметка B" --depth 2 --direction out
python3 ~/.claude/skills/obsidian-context/scripts/context.py --start "MOC Python" --preview   # cheap '## Суть'/summary hint per node
```

- `--mode narrow` (default: depth 1, ≤12 notes, ≤5 neighbors/node) is for
  "what's immediately around this one note". `--mode deep` (depth 2, ≤40
  notes, ≤10 neighbors/node) is for building a candidate set before
  research. Override any single number with `--depth`/`--max-notes`/
  `--max-neighbors` if the task genuinely needs it — don't do that by
  default just to get more results.
- `--direction out` (outlinks only), `back` (backlinks only, i.e. what
  points at the start notes), or `both` (default).
- If a `--start` title matches more than one file, the script refuses to
  guess: it reports `ambiguous` with every candidate path. Pick the right
  one with the user or with an `obsidian-search --query` first, then pass
  the exact path.
- `--preview` attaches each node's `## Суть` (or YAML `summary` for older
  notes that predate it) — genuinely useful for deciding what's worth
  reading next, but it is a preview the script pulled, not something you've
  read. Don't cite it as evidence; open the file for that.

## Reading the report

Nodes are grouped by level; each one shows its predecessor and the edge
that reached it (`wikilink`/`embed`/`frontmatter:<field>`, `outlink` or
`backlink`). A `⛔` marker means that node's own expansion was capped or
skipped — most often `max_neighbors_reached(N found)` (there were more
neighbors than the limit; the ones shown are what fit, not a ranked top-N)
or `traversal_excluded_folder` (the node lives under a daily-note/archive
folder and wasn't expanded *from*, per the vault's default — it still shows
up as a leaf).

**Repeated connections** (the script's cycle handling: `A → B → A` etc.)
are listed separately at the bottom, not silently dropped and not
re-visited — say a note is connected multiple ways if that's what the
report shows, rather than only mentioning the first path found.

**Broken/unresolved links** are also listed separately — a wikilink whose
target doesn't exist, or whose title matches more than one file. These are
worth surfacing to the user (especially if they're about to write a note
near one), not silently skipped.

## What this skill does not do

- It doesn't read the notes it finds (aside from the optional cheap
  preview) — treat every node as "found", not "read", until you actually
  open it.
- It doesn't add semantic neighbors ("notes about a similar topic with no
  link between them") — this is structural graph traversal only. If the
  user wants topically-related notes that aren't linked yet, that's a
  separate `obsidian-search` query or a job for the future
  `obsidian-semantic-search` skill (not built yet in this project).
- It doesn't write anything to the vault.
