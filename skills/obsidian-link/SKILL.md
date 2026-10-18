---
name: obsidian-link
description: Find broken/ambiguous wikilinks, check whether two Obsidian notes are already linked, and propose or apply a well-explained cross-link between them (article, heading, or exact-paragraph granularity) in the vault's controlled relation vocabulary. Use this whenever the user wants to connect, cross-reference, or link notes together; asks what links are broken or missing; wants to relate a new article to existing ones; or mentions relationships like prerequisite, alternative, contradicts, or example between topics. A shared tag between two notes is not by itself a reason to link them — this skill expects (and records) an actual explanation for every proposed link.
---

# obsidian-link

Two different jobs, both mechanical once the *relationship itself* is
Claude's judgment call: (1) find links that don't resolve, so they can be
fixed or flagged; (2) turn a decided relationship into a correctly-placed,
idempotent wikilink. Full spec: `docs/spec/skills/06-obsidian-link.md`
(US-006); relation vocabulary and limits in `L1–L6`,
`docs/spec/defaults.md`. Runs from
`~/.claude/skills/obsidian-link/scripts/link.py`.

## Finding broken links

```bash
python3 ~/.claude/skills/obsidian-link/scripts/link.py find-broken --scope "zettelkasten/notes"
```

Omit `--scope` to scan the whole vault (fine for a vault this size; scope
it down for a huge one). Each entry is `not_found` (target doesn't
resolve to any file) or `ambiguous` (matches more than one file - Obsidian
itself would silently pick the shortest path; this report does not, so you
can decide). A wikilink-looking string inside a fenced code block (e.g. a
DataviewJS template placeholder `[[${m.file.path}]]`) is correctly not
reported here - it isn't a real link.

## Before proposing anything: check idempotency

```bash
python3 ~/.claude/skills/obsidian-link/scripts/link.py check-existing --source "notes/A.md" --target "notes/B.md"
```

`propose` runs this itself and refuses (reports `already_linked`, exit 1)
unless you pass `--force` - a shared tag or topic is genuinely not enough
justification to add a second link where one already exists.

## Proposing a link

```bash
python3 ~/.claude/skills/obsidian-link/scripts/link.py propose \
  --source "notes/A.md" --target "notes/B.md" --relation contradicts \
  --reason "B описывает альтернативный механизм для того же случая, с противоположным выводом" \
  --out /tmp/link_proposal.json
python3 ~/.claude/skills/obsidian-link/scripts/link.py apply --proposal /tmp/link_proposal.json
```

- `--relation` should be one of the vault's controlled vocabulary
  (`prerequisite`, `clarifies`, `applies`, `example`, `alternative`,
  `contradicts`, `derived-from` by default - check
  `obsidian-metadata list-vocab` for a vault-specific list). These are
  this skill family's own schema, not something Obsidian itself
  recognizes or enforces.
- `--reason` is not optional and ends up next to the link in the article -
  "found by search" is not a reason, "B описывает альтернативный
  механизм..." is.
- Default placement is a bullet in the `## Related` section (L3), built
  through the same `append-section` mechanism `obsidian-revise` uses, so
  re-running the same proposal twice does not duplicate the bullet.
- `--granularity article` (default) links the whole target note.
  `--granularity heading --target-heading "..."` links a specific section.
  `--granularity block --target-heading "..." --target-paragraph
  "exact substring"` assigns the target paragraph a stable `^block-id`
  (reusing one already there rather than adding a duplicate) and links to
  that exact paragraph - use it when the connection is really to one
  specific claim, not the whole article (L4).
- `--existing-new-links-count N`: tell it how many *other* new links
  you've already proposed for this same `--source` in the current pass -
  past 5 (L5's default) it warns, it doesn't refuse, but exceeding the
  cap without a reason worth stating to the user isn't the point of the
  default.

## Inline mentions are not this skill's job

Rewriting a sentence so it *contains* the new wikilink (rather than adding
a bullet to Related) is prose editing - use `obsidian-revise propose --op
replace-section` for that, with the wikilink included in the text you
supply. This skill's `propose` only ever appends a Related-section bullet
or assigns a block id; it does not rewrite existing sentences.

## What this skill does not do

- It doesn't invent a relationship - if you can't articulate `--reason` in
  one clear sentence, the link likely isn't ready to propose yet.
- It doesn't distinguish a *discovered* semantic neighbor (no real edge
  yet) from an *existing* wikilink anywhere in its own state - `find-broken`
  and `check-existing` both work off real wikilinks/frontmatter-links only.
  A "these seem related but nothing links them" observation comes from
  `obsidian-search`/`obsidian-context`, not from this skill.
- It doesn't call `obsidian-index-sync` (skill 18, not built) after an
  applied change - say so rather than implying the index is current.
