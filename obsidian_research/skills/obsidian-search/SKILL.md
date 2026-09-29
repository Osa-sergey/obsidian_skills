---
name: obsidian-search
description: Find notes in a connected Obsidian vault by filename, title, alias, heading or full text (via the vault's Omnisearch HTTP server), or list every file in a vault folder with no text query at all. Use this whenever the user wants to find, locate, search for, or look up a note/file/topic "in my vault", "in my notes", "in Obsidian", or "in my knowledge base" — even if they never say the word "search". Also use it proactively as the first step before creating a new note (to check whether one already exists), before linking or citing something from the vault, or before running obsidian-context/obsidian-research, since those need real vault paths to work from. Trigger on mentions of MOC, HUB, vault folders, or "do I already have a note about X". Requires a vault connected via the bin/obsidian-vault CLI in this repo.
---

# obsidian-search

Finds candidate notes and reports *where* they were found and *why* it's a
match — it never reads a whole note or judges relevance beyond that. Reading
and judging relevance are the next skills' job (obsidian-context,
obsidian-research) or a plain `Read` call once you have a path. Full spec:
`docs/spec/skills/01-obsidian-search.md` (US-001); defaults `S1–S6` and
`REQ-RET-0003` in `docs/spec/defaults.md` (both paths relative to this
project's root, i.e. the `obsidian_research/` folder — see below).

## Before the first call

This skill runs from `~/.claude/skills/obsidian-search/scripts/search.py`
regardless of which project you're in — that path is stable once
`install-skills` has run, so use it directly rather than a path relative to
the current working directory (the working directory is whatever project
you're actually in, not this skill's own folder).

`bin/obsidian-vault` (setup only: register/connect/doctor) is *not*
symlinked the same way, so resolve this project's root from the
already-stable skill symlink first:

```bash
OBS_ROOT="$(cd "$(dirname "$(readlink -f ~/.claude/skills/obsidian-search)")/.." && pwd)"
python3 "$OBS_ROOT/bin/obsidian-vault" list
```

If the current project isn't connected to a vault yet, either it already
has `.claude/obsidian-vault.yaml` pointing at a registered vault, or you
need to register/connect one:

```bash
python3 "$OBS_ROOT/bin/obsidian-vault" register <vault_id> --path /path/to/vault --port 51361
python3 "$OBS_ROOT/bin/obsidian-vault" connect <vault_id> --project .
```

Ask the user for the vault path/port if you don't have it — don't guess a
path. Once connected, every script call below resolves the vault
automatically; you only need `--profile` to target a *different* vault than
the one connected to the current project.

## Running a text search

```bash
python3 ~/.claude/skills/obsidian-search/scripts/search.py --query "GraphRAG обновление графа" --mode deep
python3 ~/.claude/skills/obsidian-search/scripts/search.py --query "python" --filters tag=MOC,folder=zettelkasten
python3 ~/.claude/skills/obsidian-search/scripts/search.py --query "GraphRAG" --format json   # for programmatic use
```

- `--mode narrow` (default) is for "find this one specific note" — top 5,
  name/title/alias first. `--mode deep` is for casting a wider net before
  research or placement decisions — top 20, text search included from the
  start.
- `--filters key=value,key=value` supports `tag=`, `folder=`, and any
  frontmatter field (`status=draft`, `type=concept`, ...). Filters are
  applied *after* Omnisearch — the script reads each candidate's
  frontmatter, so filtering doesn't cost extra Omnisearch calls.
- The script expands a query into RU/EN/abbreviation variants only when the
  vault profile's `term_variants` has an entry for it — it will never
  invent a translation on its own. If you know the vault uses a specific
  abbreviation or bilingual pair a lot, suggest the user add it to their
  profile (`config/vault_profile.example.yaml` shows the shape) rather than
  trying to work around it query by query.

## Listing a folder with no query (`REQ-RET-0003`)

```bash
python3 ~/.claude/skills/obsidian-search/scripts/search.py --folder "PARA/projects" --recursive true
python3 ~/.claude/skills/obsidian-search/scripts/search.py --folder "PARA/projects" --recursive false
```

This never touches Omnisearch and never truncates to a top-k — "all the
files in this folder" means *all* of them (minus the vault's scope
excludes). Use it, not a body-text search, when the user just wants to
browse a folder or the whole folder itself already answers the question.

## Reading the report

The Markdown table's **Совпадение** (match type) column is ranked, strongest
first: `exact_filename` / `filename_without_prefix` → `yaml_title` →
`alias_exact` → `heading_h1` → the `*_contains` variants → plain `text`
(Omnisearch matched somewhere in the body only). Lead with the strongest
tier when you tell the user what you found; don't present a `text` match
with the same confidence as an `exact_filename` one.

A ⚠️`legacy-moc`/⚠️`legacy-hub` flag next to a result means the filename
*looks* like a MOC/HUB (e.g. `MOC Python.md`, no underscore) but does not
use the vault's required `MOC_`/`HUB_` prefix. **Never rename it and never
silently treat it as a compliant MOC/HUB** — point it out to the user as a
naming-convention gap if it's relevant to the task; migrating it is a
separate, explicit decision (this is real, common in vaults that predate
this skill set — see acceptance.md's "Найден старый MOC/HUB без префикса").

If the report opens with `omnisearch_unavailable`, say so plainly instead of
presenting the results as a normal run — the fallback only matched
filename/title/aliases/H1, not full body text, so recall is genuinely lower
for `deep` queries. Suggest enabling Omnisearch's HTTP server in Obsidian
(vault must be open) if it matters for the task at hand.

## What this skill does not do

- It doesn't read note bodies beyond the cheap frontmatter/H1 peek needed
  for match classification — the `excerpt` in the report is Omnisearch's
  own preview, not a verified read. Read the file before citing it as a
  fact.
- It doesn't rank by "relevance to the user's actual question" beyond
  Omnisearch's own text score — that judgment, and any graph/context
  expansion, is `obsidian-context`'s and `obsidian-research`'s job.
- It doesn't write anything to the vault.
