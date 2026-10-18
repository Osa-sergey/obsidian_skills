---
name: obsidian-workflow
description: Route a complex, multi-part Obsidian request across the other skills — find sources, gather context, research, draft or revise articles, link and tag them, place them in MOCs and HUBs — and produce one honest final report instead of leaving several separate results scattered across a conversation. Use whenever a request needs more than one of the other obsidian-* skills to actually finish (e.g. "research X and write it up", "find what's missing on Y and prepare articles", "reorganize this MOC and fix its links"), not for a single lookup or a single edit — those go straight to the one skill that does them.
---

# obsidian-workflow

This skill doesn't do retrieval, writing, or research itself - it decides
**which already-built skills to call, in what order**, for a request
shaped like "do several of these things for me." Full spec:
`docs/spec/skills/10-obsidian-workflow.md` (US-012/US-014/US-015). Runs
from `~/.claude/skills/obsidian-workflow/scripts/workflow.py`, which
handles two small, genuinely mechanical pieces (which skills exist right
now, and tallying up a run's results) - the routing itself is judgment
applied to the request, which is what the rest of this file is for.

## Check what's actually built before promising a step

```bash
python3 ~/.claude/skills/obsidian-workflow/scripts/workflow.py list-skills
```

The roster keeps growing; don't assume a skill from the spec's full list
of 19 exists just because it's named below. As of this writing, skills
14 (`obsidian-retrieve`), 16 (`obsidian-evidence`), 17 (`obsidian-qa`), 18
(`obsidian-index-sync`), 11-13 (`obsidian-query`/`-query-builder`/
`-semantic-search`) are **not built** - every route below says what
stands in for them today, and none of them should be name-dropped in a
final report as if they ran.

## Three request shapes, three routes

**Narrow QA** ("what does X do", "where do I already have a note about
Y") - no `obsidian-qa` yet, so compose the answer yourself from what you
actually read:

```
obsidian-search → [obsidian-context if the first hit needs neighbors] → obsidian-fragment-reader → your own cited answer
```

**Deep research and knowledge development** ("research X and write it
up", "find what's missing on Y") - the common, multi-step case:

```
obsidian-search(deep) + obsidian-context(deep)      # in place of obsidian-retrieve, not built
  → obsidian-gap-search                              # only when the goal is finding under-covered questions
      → (external research authorized?) obsidian-research on the validated query plan
  → obsidian-research                                # synthesis over what was actually read
  → placement decision (existing article close enough? → obsidian-revise; genuinely new? → obsidian-author)
  → obsidian-link + obsidian-metadata                 # cross-links and schema-consistent frontmatter
  → obsidian-moc                                      # file the result into the right map(s)
  → obsidian-hub                                       # only if this changes a work/learning route, not every time
```

The placement decision (existing vs. new, which MOC, whether the HUB's
route changes) is exactly workflows.md's "Placement decision" checklist -
your judgment, informed by what `obsidian-search`/`obsidian-context`
actually found, not something a script decides here.

**Reorganize / maintain** ("fix broken links in this MOC", "tidy up this
HUB's stages"):

```
obsidian-link find-broken (+ obsidian-moc list-hierarchy for cycle/consistency checks)
  → obsidian-revise / obsidian-moc / obsidian-hub for the specific fixes
```

## Collect every write, then summarize once

Every `apply` call across `author`/`revise`/`moc`/`hub`/`link`/`metadata`
prints a JSON `ChangeRecord` (`path`, `operation`, `status`, `detail`).
Keep them as you go, then produce one final tally instead of leaving the
user to piece together several scattered JSON blobs:

```bash
python3 ~/.claude/skills/obsidian-workflow/scripts/workflow.py summarize-run --records-file records.json
```

`records.json` is just a JSON array of whatever those `apply` calls
printed. The summary groups them by status, and - this is the part worth
never skipping - **refuses to imply the whole batch succeeded if anything
didn't**: a single `conflict` or `error` record flips `all_ok` to false
and the Markdown report prints an explicit "пакет не полностью применён"
warning (acceptance.md: "Отчёт не объявляет весь пакет готовым"). It also
always reports `index_dirty: true` the moment any record is `applied`,
since `obsidian-index-sync` (skill 18) doesn't exist yet - carry that
warning into whatever you tell the user, don't quietly drop it.

## What this skill does not do

- It doesn't retrieve, read, write, or research anything itself - every
  actual step is one of the other skills; this one only sequences them
  and reports on what they did.
- It doesn't decide article count, folder placement, new tags, or
  navigation updates by formula - those stay Claude's call per request
  (W3), informed by what the called skills actually returned.
- It doesn't run automatically on a schedule or in response to a vault
  change (W6) - every workflow run is an explicit request.
- It doesn't call `obsidian-index-sync` itself, because it doesn't exist
  in this project yet - `summarize-run`'s `index_dirty` flag is the
  closest honest substitute: a clear signal to carry into the final
  report, not a fix.
