---
name: obsidian-evidence
description: Turn a set of candidate notes (usually obsidian-retrieve's CandidateSet) or any addressed fragment requests into a deduplicated, verified EvidenceItem[] — one real fragment per claim, with a quote checked to actually appear in the text and a read-cost estimate. Use this whenever a task needs to back specific claims/answers with citable evidence rather than just "here are some relevant notes" — before obsidian-research writes conclusions into a report, before obsidian-qa answers a question that needs citations, or whenever several claims might point at overlapping or duplicate source text that shouldn't be re-read or re-quoted separately. Do not use this for a plain "find notes about X" — that's obsidian-search/obsidian-retrieve; this skill assumes you already have candidates and need to turn them into checked, per-claim evidence.
---

# obsidian-evidence

Fetches real text via `obsidian-fragment-reader`'s own primitive
(`read_fragment`), collapses duplicate/contained requests so the same
passage isn't fetched or quoted twice, and — the part that actually
catches mistakes — verifies that any quote marked `directness: direct`
is a real, verbatim substring of the fragment it's attached to. Full
spec: `docs/spec/skills/16-obsidian-evidence.md` (US-002/US-003); the
fetch/dedup/validate logic lives in `lib/obsidian_common/evidence.py`.
Runs from `~/.claude/skills/obsidian-evidence/scripts/evidence.py`.

**Division of labor**: this script never decides which claim a fragment
supports, how direct the support is, or how confident to be — that's
your judgment, made by actually reading the fetched text. What it does
mechanically: fetch real text at a real address, deduplicate overlapping
requests, and catch a quote that doesn't actually appear in the source
before it goes out as if it were verbatim (same "не угадывать" principle
`obsidian-gap-search` applies to author names, applied here to quotes).

## Workflow

**1. Get addresses to fetch.** The normal path is straight from
`obsidian-retrieve`'s JSON output:

```bash
python3 ~/.claude/skills/obsidian-retrieve/scripts/retrieve.py search \
  --query "..." --format json > /tmp/candidates.json

python3 ~/.claude/skills/obsidian-evidence/scripts/evidence.py fetch-from-candidates \
  --candidates-file /tmp/candidates.json --format json > /tmp/fetched.json
```

Derives one request per candidate that has a `semantic_match` — a
`section`/`subsection` match re-resolves by heading path (robust to line
drift since it was indexed), a `chunk`/`callout` match uses its exact
line range, an `article` match reads the whole file. Candidates with no
`semantic_match` (omnisearch/graph-only hits) come back in
`no_addressed_node` — there's no addressed node to fetch automatically
for them; read those via `obsidian-search`'s excerpt or address them by
hand with plain `fetch` below.

For requests you're assembling yourself (not from a CandidateSet), use
`fetch` directly with a JSON array of `{tag, path, heading?, block_id?,
line_range?}`:

```bash
python3 ~/.claude/skills/obsidian-evidence/scripts/evidence.py fetch \
  --addresses-file /tmp/addresses.json --format json > /tmp/fetched.json
```

`tag` is your own label (a claim id, the source path, anything) — two
requests that resolve to the exact same range, or where one fully
contains another, are fetched once and both tags land in that fragment's
`requested_for`; note that non-containing partial overlaps are **not**
merged (each gets its own entry — a known simplification).

**2. Read the fetched fragments yourself** (from `/tmp/fetched.json` or
the `md`-formatted stdout) and decide, per claim: which fragment actually
supports it, whether that support is `direct` (the fragment states it) or
`interpretation` (you're inferring it), a short `quote` (only for
`direct`) or `paraphrase`, and your `confidence`. Assemble this as a JSON
array — one object per claim — with at least `claim`, `fragment_id`,
`directness`, `confidence`, `retrieval_methods`, and `quote` or
`paraphrase`.

**3. Validate before presenting it as evidence:**

```bash
python3 ~/.claude/skills/obsidian-evidence/scripts/evidence.py validate \
  --evidence-file /tmp/evidence.json --fetched-file /tmp/fetched.json
```

Catches: a `fragment_id` that wasn't actually fetched or didn't resolve,
a missing `claim`, and — the important one — a `direct` item whose
`quote` isn't a real (whitespace-normalized) substring of that fragment's
text. **Fix every error before treating the evidence set as final** — a
failed quote check usually means the claim was paraphrased and
mislabeled, not that the check is wrong.

**4. Render the final report:**

```bash
python3 ~/.claude/skills/obsidian-evidence/scripts/evidence.py render \
  --evidence-file /tmp/evidence.json --fetched-file /tmp/fetched.json
```

Adds `read_cost_tokens` per item (from the real fragment length) and a
total, and re-runs the same validation, surfacing any remaining errors at
the top rather than silently rendering broken evidence as if it were
clean.

### Related

[§3.14 obsidian-retrieve](../obsidian-retrieve/SKILL.md) is the usual
source of candidates. [§3.15
obsidian-fragment-reader](../obsidian-fragment-reader/SKILL.md) is what
this skill's `fetch` calls under the hood — use it directly instead when
you just need to read one known address, no claim-verification involved.
[§3.17 obsidian-qa](../obsidian-qa/SKILL.md) is a typical consumer of a
finished EvidenceItem[].
