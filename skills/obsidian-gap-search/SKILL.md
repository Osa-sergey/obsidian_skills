---
name: obsidian-gap-search
description: Evaluate how well a HUB, MOC, or topic is actually covered by a connected Obsidian vault, and turn a confirmed or discovered gap into a ranked plan of external search queries — without ever running a web search or writing to the vault. Use whenever the user names a suspected gap ("мало о X", "not enough on Y") and wants it checked before searching the web; asks what's missing or under-covered in a HUB/MOC/topic; or wants search queries prepared for external research. Also use it before obsidian-research does actual external research, so the queries it's given are grounded in what's really missing, not guessed. Never claims a web search happened — its output status is always "planned".
---

# obsidian-gap-search

Two outputs, both provisional until someone actually reads the result:
`CoverageGap[]` (what's missing, and how confident that is) and an
`ExternalSearchQueryPlan` (what to search for, ranked, never executed
here). Full spec: `docs/spec/skills/19-obsidian-gap-search.md` (US-015);
ADR-0007 explains why this is a separate step from `obsidian-research`.
Runs from `~/.claude/skills/obsidian-gap-search/scripts/gap_search.py`.

**This skill never opens a browser and never creates a note.** Its whole
job ends at a validated, ranked list of queries someone else executes -
`obsidian-research`, or the user by hand.

## 1. Read the target's checklist

```bash
python3 ~/.claude/skills/obsidian-gap-search/scripts/gap_search.py read-target --hub "Hubs/HUB_RAG.md"
python3 ~/.claude/skills/obsidian-gap-search/scripts/gap_search.py read-target --moc "Maps/MOC_RAG - Индексация.md"
```

Pulls out exactly what should be checked against: a HUB's `purpose`,
`terms`, and every stage's goal/materials/action/expected_result; a MOC's
`perspective`, `perspective_question`, `summary`, `terms`. This is the
"read its summary and structure first" step (algorithm §6 step 1) done
once, structured, instead of re-parsing the file by eye.

## 2. Check the hint, or find what's under-covered without one

**With a hint** ("мало о динамическом обновлении GraphRAG"): check that
specific claim against synonyms, English terms, and neighboring sections
before trusting it.

**Without a hint**: compare the target's own terms/stage goals against
what's actually findable - don't just list every topic the vault doesn't
mention, prioritize what the HUB/MOC's own stated purpose actually needs.

Either way, batch the candidate terms (both languages, plus anything from
`read-target`) through one call:

```bash
echo '["incremental GraphRAG update", "инкрементальное обновление графа", "chunking"]' > terms.json
python3 ~/.claude/skills/obsidian-gap-search/scripts/gap_search.py check-coverage --terms-file terms.json
```

**A missing hit does not by itself prove a gap** (REQ-RET-0004) - a topic
can be covered under different wording or buried in a section that ranks
low on lexical search. Read what *is* found (via
`obsidian-fragment-reader`) before concluding it doesn't cover the
question; only decide `missing`/`shallow`/`stale`/`contradictory`/
`uncertain` after that read, with the confidence that actually reflects
how much you checked.

## 3. Build the plan, then validate it before showing anyone

Assemble `gaps.json` (`CoverageGap[]`) and `plan.json`
(`ExternalSearchQueryPlan[]`, one entry per query, `"status": "planned"`
always) yourself - the research-question breakdown and the actual query
wording are judgment calls this script doesn't make. Then:

```bash
python3 ~/.claude/skills/obsidian-gap-search/scripts/gap_search.py validate-plan --plan-file plan.json
```

Catches, mechanically, every entry that:
- has `status` other than `"planned"` (this skill never claims a search
  ran - `obsidian-research` earns `searched`/`verified` later, by
  actually opening something);
- is missing a required field (`research_question`, `query_text`,
  `language`, `purpose`, `expected_source_type`, `stop_criterion`);
- near-duplicates another entry's `query_text` (algorithms.md §6 wants
  non-repeating queries - a warning, not a blocker, but worth trimming);
- names an `author` **without** `author_source_path` +
  `author_source_quote`, or where that quote/name don't actually appear
  verbatim in the cited file. **This is the one hard rule that never
  bends**: REQ-RET-0005 says a personal query only exists for an author
  actually found in something you read, with its address - never a
  guessed or "probably correct" name. If `validate-plan` rejects an
  author entry, drop the `author` field rather than trying to patch the
  quote to pass.

## 4. Render the final report

```bash
python3 ~/.claude/skills/obsidian-gap-search/scripts/gap_search.py render --gaps-file gaps.json --plan-file plan.json
```

Runs the same validation first and **refuses to render a plan that fails
it** - fix the flagged entries rather than rendering around them. If
internal coverage turns out sufficient, say so and render an empty or
shortened plan instead of padding it with weak queries just to have
output.

## After this skill

If the user actually wants external research done, hand the validated
plan's queries to `obsidian-research` - it opens sources, verifies them,
and does the synthesis. Findings only exist after something is actually
read; this skill's output describes what to look for, never what was
found. If the user only wanted the plan, stop here - render's output is a
complete, standalone result on its own.

## What this skill does not do

- It never runs a web search, opens a URL, or creates/edits any vault
  file - every output is text for you or the user to act on next.
- It doesn't decide *which* gaps are worth pursuing beyond what
  `validate-plan` can check mechanically - significance, research-question
  framing, and query wording stay your judgment.
- It doesn't resolve RAPTOR-level "semantic" coverage - skill 13 isn't
  built in this project; coverage checking here is Omnisearch/structural
  only, so a genuinely paraphrased treatment of a topic with no shared
  vocabulary can still look like a gap. Say so as a limitation rather than
  presenting `missing` with high confidence when the check was shallow.
