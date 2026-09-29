---
name: obsidian-research
description: Research a question against notes already in a connected Obsidian vault (and, if the user allows it, outside sources) — compare approaches, surface contradictions and gaps, and produce a research note with every conclusion traceable to a specific file+heading. Use this whenever the user asks to research, investigate, compare, synthesize, "what does my vault say about X", "summarize what I have on X", find contradictions/gaps in their notes, or wants a written research note/report out of their vault rather than a quick answer. Pairs with obsidian-search (to find candidates) and obsidian-context (to gather their neighborhood) as its own first steps — invoke this skill for the synthesis, not as a replacement for those two when all that's needed is a lookup.
---

# obsidian-research

Turns a set of *read* materials into a research note: synthesis, findings,
comparisons, contradictions, gaps, and recommendations, each traceable to a
specific file and heading. Full spec:
`obsidian_research/docs/spec/skills/03-obsidian-research.md` (US-003);
defaults `R1–R6` in `obsidian_research/docs/spec/defaults.md`.

**The comparison and judgment work is yours, not a script's** — no script
can reliably decide whether two notes genuinely contradict each other or
merely use different words. What the bundled script *does* do reliably:
addressed reading, catching a citation that points at a file/heading that
doesn't actually exist, spotting when two notes cite the same primary
source, and rendering your findings into the vault's fixed note structure.
Use it for that; do the reading and reasoning yourself.

## Skills 14–17 (`obsidian-retrieve`, `obsidian-fragment-reader`,
`obsidian-evidence`, `obsidian-qa`) are not built in this project yet.
Until they exist, this skill assembles its own material directly:

1. **Find candidates** — call `obsidian-search` (`scripts/search.py`) for
   the question's key terms, `--mode deep`.
2. **Gather their neighborhood** — call `obsidian-context`
   (`scripts/context.py`) from the strongest candidates, `--mode deep`, to
   catch related notes that don't rank high on text search alone.
3. **Read addressed fragments, not whole vaults** — for each candidate
   worth checking, read its `## Суть` first (via `obsidian-context
   --preview` or `research_note.py fragment --heading Суть`), then pull
   the specific sections that actually bear on the question:

   ```bash
   python3 skills/obsidian-research/scripts/research_note.py fragment \
     --path "zettelkasten/notes/GraphRAG (Microsoft).md" --heading "Краткое описание"
   ```

   A note that only turned up in search but was never opened is
   "found", not "read" — never use it as a basis for a claim (this is the
   single most important invariant in the whole spec: foundation.md §2.3
   rules 1–2, and acceptance.md's "Статья есть только в выдаче, но не
   читается").

4. **Build the claim → evidence map as you go** — for every claim that
   will end up in the note, record `{claim, path, heading}` (and ideally
   `directness`: is this the primary source or a note paraphrasing one?).
   Before writing the note, validate it against the live vault:

   ```bash
   python3 skills/obsidian-research/scripts/research_note.py validate --evidence evidence.json
   ```

   This catches a hallucinated path or a heading that doesn't exist —
   fix every non-`resolved` entry before it goes into the note. It cannot
   verify you actually *read* the text; that discipline is still on you.

5. **Collapse repeated primary sources.** If two vault notes cite the same
   external publication, that's one independent basis, not two:

   ```bash
   python3 skills/obsidian-research/scripts/research_note.py dedup-sources --sources sources.json
   ```

   A `confirmed_same_source` group (same URL) can be collapsed outright; a
   title-only heuristic group needs a quick look before you treat it the
   same way.

6. **Render the note** once the content is settled:

   ```bash
   python3 skills/obsidian-research/scripts/research_note.py render \
     --findings findings.json --out "PARA/resources/Research - <topic>.md"
   ```

   `findings.json` fields: `suti` (two-sentence gist), `scope`,
   `synthesis`, `findings[]`, `comparisons`, `contradictions[]`, `gaps[]`,
   `implications[]`, `sources[]`, `claim_evidence_map[]` (each row:
   `claim`, `source`, `fragment`, `directness`). Omit `--out` to preview the
   rendered Markdown on stdout before writing anything.

## Structure and honesty rules that don't move

- **Order**: synthesis → findings → comparisons/contradictions → gaps →
  implications → what this means for the vault (R2). The `render`
  subcommand already enforces this shape — don't reorder it by hand.
- **Show contradictions, don't quietly resolve them.** If two sources
  disagree, say so and give your synthesis *with* the disagreement visible,
  not instead of it (R5).
- **Separate fact, interpretation, and your own new conclusion.** A vault
  note's paraphrase of an external source is not the same as that source
  (foundation.md §2.3 rule 4–5) — say "per note X, which cites Y" rather
  than treating the note as the primary source itself.
- **Name what's out of scope.** If the question needed external sources and
  the user hasn't authorized that for this run (`R1`: narrow is vault-only;
  deep may use provided/local sources; the open web only when the user
  actually asked for it), say the research is vault-only and what that
  limits, instead of quietly narrowing the question. For gap-driven
  external-search planning specifically, the normative skill is
  `obsidian-gap-search` (§3.19) — not built in this project yet either;
  until it exists, note candidate gaps in the research note's own "Пробелы"
  section rather than fabricating a formal query plan.
- **Writing the note is not applying it to the vault's link/MOC structure.**
  `render --out` creates the research-note file itself (and only if it
  doesn't already exist, unless `--overwrite`). Linking it into a MOC,
  cross-linking it from related articles, or updating those articles is
  `obsidian-link`/`obsidian-moc`/`obsidian-revise`'s job — not built in this
  project yet. If a real file gets written to the vault, say so plainly and
  flag that `obsidian-index-sync` (skill 18, also not built yet) has not
  run, so any semantic index is stale until it does — never imply the
  vault's search index is now up to date.
