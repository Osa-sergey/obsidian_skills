---
name: obsidian-moc
description: Create and grow hierarchical Maps of Content (MOC) in a connected Obsidian vault — each with an explicit perspective, a required summary and key terms, at most one main parent, and cycle-checked structure. Use whenever the user wants to organize notes by topic, build or extend a MOC/map-of-content, find where a new article belongs in the existing map, or asks to see how topics relate hierarchically. Also use it to add an article or a child MOC into an existing map — it keeps both sides consistent (the MOC's visible list and the linked file's own metadata) rather than just editing one side.
---

# obsidian-moc

A MOC is a curated, perspective-specific view of a topic - **not** a
folder and not "everything tagged X." Every MOC answers one explicit
question (`perspective_question`) from one explicit angle
(`perspective`); a different angle on the same topic is a *different*
MOC, not a section inside this one. Full spec:
`docs/spec/skills/08-obsidian-moc.md` (US-007); ADR-0003 explains the
one-main-parent design. Runs from
`~/.claude/skills/obsidian-moc/scripts/moc.py`, and every write goes
through the same propose/apply engine `obsidian-revise` uses - nothing
here invents a second way to write a file safely.

## Before creating one: look at what already exists

```bash
python3 ~/.claude/skills/obsidian-moc/scripts/moc.py list-hierarchy
```

Shows every real MOC (files with `type: moc` in frontmatter - a
`MOC_`-looking filename alone is never trusted on its own, per
foundation.md §2.5) as a parent/child tree with each one's perspective.
Check this - and `obsidian-search` for the topic itself - before proposing
a new MOC; a near-duplicate topic+perspective combination usually means
you found the right MOC to extend instead (`add-article`/`add-child`),
not a reason for a new file.

## Creating a MOC

```bash
python3 ~/.claude/skills/obsidian-moc/scripts/moc.py check-name --title "RAG - Индексация"
python3 ~/.claude/skills/obsidian-moc/scripts/moc.py new \
  --title "RAG - Индексация" --perspective architecture \
  --perspective-question "Как устроена индексация RAG?" \
  --summary "Карта практик индексации: chunking, embeddings, обновление." \
  --terms "indexing,chunking,embeddings" --parent "Maps/MOC_RAG.md" --tags "rag" --apply
```

- `check-name` runs REQ-FND-0001's global uniqueness check against
  `MOC_<title>.md`, not just the title text - always run it (or let `new`
  refuse) before committing to a name.
- `--perspective` and `--perspective-question` are both required and both
  meaningful: the perspective is a short code (`theory`, `architecture`,
  `implementation`, `operations`, `evaluation`, `use-cases` are the
  starting vocabulary - `check-tag`/`list-vocab` on `obsidian-metadata`
  shows this vault's actual one), the question is what makes that angle
  concrete. Neither is decorative - they should actually change which
  articles belong here versus in a sibling MOC on the same topic.
- `--summary` is required and becomes both the YAML field (used for cheap
  discovery without opening the file) and the body's `## Summary` -
  supply the same real sentence for both, don't leave one as a stub.
- `--parent`, if given, must already exist and already be a real MOC
  (`type: moc`) - a brand-new MOC can't yet be part of a cycle, so `new`
  doesn't need `check-cycle` itself, but a later `add-child` does (see
  below).
- Without `--apply` this only previews the assembled file - read it before
  writing.

## Growing an existing MOC

```bash
python3 ~/.claude/skills/obsidian-moc/scripts/moc.py add-article \
  --moc "Maps/MOC_RAG - Индексация.md" --article "notes/Chunking стратегии.md" \
  --annotation "Обзор 8 стратегий chunking с компромиссами" --apply

python3 ~/.claude/skills/obsidian-moc/scripts/moc.py add-child \
  --parent-moc "Maps/MOC_RAG.md" --child-moc "Maps/MOC_RAG - Индексация.md" \
  --annotation "Ракурс: архитектура индексации" --apply
```

Both commands write **both sides in one call**: `add-article` appends an
annotated bullet to the MOC's `## Статьи` and sets the article's own
`moc:` YAML field (foundation.md: the visible list and the field must
agree, not drift into two separately-maintained truths); `add-child` does
the same for `## Дочерние MOC` and the child's `parent_mocs`. Each side is
its own patch with its own freshness check, so a conflict on one side is
reported without silently skipping the other - re-run once both files are
current again.

`--annotation` is required and should say *why* this article belongs in
*this* MOC's perspective, not just restate its title - "справочник по
методам" tells a reader nothing an untitled link wouldn't; "сравнивает
затраты по памяти 6 подходов, важно для operations-ракурса" does.

Re-running the same `add-article`/`add-child` reports `unchanged` on both
sides rather than duplicating the bullet or the field entry. The very
first real entry replaces the `new`-generated `_нет_` placeholder instead
of leaving it dangling next to real content.

## `add-child` always checks for cycles first

```bash
python3 ~/.claude/skills/obsidian-moc/scripts/moc.py check-cycle --moc "Maps/MOC_A.md" --parent "Maps/MOC_B.md"
```

`add-child` runs this itself and refuses (exit 2, no write on either side)
if assigning `--parent-moc` as `--child-moc`'s parent would create a loop
- walk the *proposed parent's* own ancestor chain and see if it already
leads back to the child. You can run it standalone first if you want to
check before deciding.

## What this skill does not do

- It doesn't move an *existing* MOC to a different parent as a single
  command - `parent_mocs` is O7's one-main-parent field, and changing it
  on an established MOC also means updating the old parent's visible
  list; that's a structural change worth doing deliberately (build it
  from `add-child` plus an explicit `obsidian-revise` edit removing the
  stale bullet from the old parent), not something this skill automates
  in one call.
- It doesn't build the HUB Canvas view of a topic - `obsidian-moc`
  produces the hierarchical map; `obsidian-hub` builds the visual
  work/learning route that *selects from* several MOCs and articles.
- It doesn't call `obsidian-index-sync` (skill 18, not built) after a
  write - every applied change says so; pass that on rather than implying
  the vault's search index now reflects it.
