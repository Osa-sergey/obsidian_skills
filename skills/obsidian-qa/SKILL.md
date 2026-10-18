---
name: obsidian-qa
description: Answer a precise question from a connected Obsidian vault at minimal token cost — a short, cited answer traceable to the smallest sufficient set of fragments, not a full research pass. Use whenever the user asks a specific, answerable-from-notes question ("what does my vault say about X", "what's the difference between A and B in my notes", "do I have a definition of Y") and wants a direct answer rather than a written report. Also covers light insight mining — spotting a pattern or contradiction across a few related fragments. If the question turns out to need a broad survey of the topic, this skill says so and hands off to obsidian-research(mode=deep) rather than quietly reading dozens of notes.
---

# obsidian-qa

The narrow half of US-002: minimal reading, an answer, and a receipt for
exactly what was read. Full spec: `docs/spec/skills/17-obsidian-qa.md`;
narrow-mode budget in `docs/spec/defaults.md` blocks `C4`/`W4`. Runs from
`~/.claude/skills/obsidian-qa/scripts/qa.py`. Skills 14/16
(`obsidian-retrieve`/`obsidian-evidence`) aren't built in this project yet
- this skill's own pipeline stands in for them, the same way
`obsidian-research` and `obsidian-gap-search` already fill equivalent
gaps elsewhere.

## The pipeline

```
question → obsidian-search(mode=narrow) → obsidian-fragment-reader for each
  addressed read → qa.py validate-evidence → answer → qa.py render
```

1. **Know the budget before you start reading:**

   ```bash
   python3 ~/.claude/skills/obsidian-qa/scripts/qa.py budget
   ```

   Narrow's default: ~6000 tokens, ≤12 notes, depth 1 if you need
   `obsidian-context` at all. This is a real ceiling, not a suggestion -
   consistently landing outside it is itself the signal this question
   needs `obsidian-research(mode=deep)` instead, per the passport's own
   escalation rule.

2. **Break the question into checkable parts**, then find candidates with
   `obsidian-search` (narrow mode: name/title/alias first). Only reach for
   `obsidian-context` if a strong hit's neighbors are actually needed -
   most narrow questions don't need graph expansion at all.

3. **Read only the addressed piece** of each candidate via
   `obsidian-fragment-reader` - a heading, a `^blockid`, a line range.
   Progressive disclosure applies here more than anywhere else in this
   skill family: a note's `## Суть`/YAML `summary` first, then the
   specific section, and the *whole file* only if truly nothing smaller
   answers the question.

4. **Build the evidence list as you read**, one entry per fact the answer
   will rely on:

   ```json
   {"question_part": "что такое GraphRAG",
    "path": "zettelkasten/notes/GraphRAG (Microsoft).md",
    "heading": "Краткое описание",
    "quote": "открытый проект Microsoft Research",
    "directness": "direct", "confidence": "high", "retrieval_method": "search"}
   ```

   `heading` / `block_id` / `line_range` - whichever `obsidian-fragment-
   reader` used to find it. `quote` is optional but, if given, must be a
   verbatim substring of what you actually read - `validate-evidence`
   checks this and will reject a quote that doesn't match, which is
   exactly the point (it catches a misremembered or invented quote before
   it reaches the user). If it's not a real quote, use `paraphrase`
   instead of forcing something into `quote` that isn't verbatim.
   `directness` is one of `direct`/`paraphrase`/`inferred`; `confidence`
   one of `high`/`medium`/`low` - both required, both checked.

5. **Validate before answering:**

   ```bash
   python3 ~/.claude/skills/obsidian-qa/scripts/qa.py validate-evidence \
     --evidence-file evidence.json --question-parts-file question_parts.json
   ```

   `--question-parts-file` (a JSON array of the parts from step 2) is
   optional but worth doing whenever the question has more than one part
   - it reports `uncovered_question_parts` for anything with zero
   evidence, which is the mechanical half of "либо явно обозначенный
   пробел" (algorithms.md §1): say plainly that a part isn't covered
   rather than answering around it. The result's `budget` section tallies
   what was *actually* read (not requested - read) against the narrow
   limits; `escalate_to_deep_research: true` means either the budget or
   coverage says this has outgrown narrow mode.

6. **Render the final answer:**

   ```bash
   echo '{"question": "...", "answer": "...", "limitations": "..."}' > answer.json
   python3 ~/.claude/skills/obsidian-qa/scripts/qa.py render --evidence-file evidence.json --answer-file answer.json
   ```

   Runs the same validation first and **refuses to render evidence that
   fails it** - fix the flagged items, don't answer around them. The
   output is the answer, an evidence table, and a read-budget report,
   automatically flagging when the budget was exceeded.

## Insight mining is the same pipeline, wider evidence

Spotting a repeated pattern, a contradiction, or an unexpected connection
across a handful of fragments still goes through the same
`evidence.json` → `validate-evidence` → `render` shape - just with
several `question_part` entries covering the different angles compared.
**The line that must not move**: if answering well genuinely requires a
broad survey of the topic (many notes, several passes, real synthesis),
that is `obsidian-research(mode=deep)`'s job. Escalate explicitly and say
why, rather than quietly reading enough notes that this stopped being
"narrow" without anyone deciding that on purpose.

## What this skill does not do

- It doesn't decide what counts as a good answer or which fragments
  matter - only that every fragment actually cited really says what's
  claimed, and that reading stayed inside a stated budget.
- It doesn't run the search or the reads itself - `obsidian-search` and
  `obsidian-fragment-reader` do that; this skill validates and formats
  what came back from them.
- It doesn't silently expand into deep research when a question turns out
  bigger than expected - it says `escalate_to_deep_research: true` and
  stops, leaving the actual hand-off to `obsidian-research` as a
  deliberate next step.
- It doesn't write anything to the vault.
