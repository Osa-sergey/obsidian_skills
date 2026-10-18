---
name: obsidian-revise
description: Propose, then (only on request) apply, an addressed edit to an existing Obsidian article — replacing a section, appending to one, updating YAML frontmatter, or upserting a machine-managed block by stable ID. Use this whenever the user wants to update, correct, add a fact to, or extend an existing note rather than create a new one; when new research contradicts or extends something already written; or after obsidian-author/obsidian-link/obsidian-metadata have decided that a change belongs to an existing file. Never rewrites a whole file or a whole section's author prose without being told exactly what the new text should be — this skill applies precise, reviewable patches, not regeneration.
---

# obsidian-revise

Every real change goes through a `propose` (builds a diff, remembers a
hash of just the touched region, never writes) then an explicit `apply`
(re-reads live, checks that region is still what `propose` saw, writes
atomically or reports a clean conflict). Full spec:
`docs/spec/skills/05-obsidian-revise.md` (US-005); ADR-0002 explains why
proposal-first. Runs from
`~/.claude/skills/obsidian-revise/scripts/revise.py`.

**Why the two steps matter**: the file you read five minutes ago may not
be the file on disk now (the user edited it in Obsidian, another skill run
touched it, etc.). `apply` catches that by hashing only the specific
section/block/frontmatter/line the edit touches - a change *elsewhere* in
the same file between propose and apply does not block your edit and is
not lost, only a change to the exact region you're touching does. A
conflict is the expected, correct outcome then - re-read the current file
and call `propose` again, never retry `apply` with the same JSON.

## The four operations

```bash
# Replace a section's own text (not its subsections) wholesale
python3 ~/.claude/skills/obsidian-revise/scripts/revise.py propose --path "notes/Статья.md" \
  --op replace-section --heading "Механизм" --new-content-file /tmp/new.md \
  --reason "новый подтверждённый факт" --sources "[[Sources/X]]" --out /tmp/proposal.json

# Add to the end of a section (creates the section if it doesn't exist)
python3 ~/.claude/skills/obsidian-revise/scripts/revise.py propose --path "notes/Статья.md" \
  --op append-section --heading "Related" --new-content-file /tmp/addition.md --out /tmp/proposal.json

# Upsert a block your own automation owns, by a stable ID you choose (idempotent re-runs)
python3 ~/.claude/skills/obsidian-revise/scripts/revise.py propose --path "notes/Статья.md" \
  --op managed-block --block-id "moc-backlinks" --heading "Related" --new-content-file /tmp/block.md --out /tmp/proposal.json

# Additive YAML merge (see obsidian-metadata for schema-validated merges)
python3 ~/.claude/skills/obsidian-revise/scripts/revise.py propose --path "notes/Статья.md" \
  --op yaml-merge --updates-file /tmp/updates.json --out /tmp/proposal.json

# Then, once you (or the user) are happy with the diff preview:
python3 ~/.claude/skills/obsidian-revise/scripts/revise.py apply --proposal /tmp/proposal.json
```

- `replace-section` swaps exactly that heading's own text; a subsection
  underneath it is untouched and re-spliced back automatically - you never
  need to include child subsections in `--new-content-file`.
- `append-section` is idempotent: appending text that's already present
  in the section reports `unchanged` instead of duplicating it. This is
  what makes "run this again on the same findings" safe.
- `managed-block` is for content *your own automation* regenerates over
  time (a computed backlink list, a saved-query result) - wrap it in a
  stable `--block-id` and re-run the same propose/apply on every update;
  it replaces in place, never duplicates. Don't use it for a human's own
  prose - that's `replace-section`/`append-section`, which leave
  everything outside the exact touched region alone.
- `yaml-merge` only *adds or overwrites the fields you pass* - existing
  keys (including ones this skill doesn't know about) survive untouched;
  list fields like `tags` are unioned, not replaced. For the same
  operation with schema/controlled-vocabulary validation first, prefer
  `obsidian-metadata propose` - it calls the same engine.

## Choosing a reason (U2 default)

Every `--reason` should be one of: a factual error, a newly confirmed
fact, a meaningful clarification, bringing something up to date, or a
useful practical example/cross-link. "This seems related" is not
sufficient grounds on its own for touching someone's existing prose -
similarity of topic is explicitly not the same as a reason to edit
(spec §3.5: "Сходство темы само по себе не является основанием").

## `propose-rename` is a report, not an action

```bash
python3 ~/.claude/skills/obsidian-revise/scripts/revise.py propose-rename --path "notes/Old.md" --new-name "New Name"
```

Checks REQ-FND-0001 uniqueness for the new name and lists every file that
currently links to the old path - genuinely useful before a rename, but
this command does not rename the file or rewrite any links (U5: merge/
split/rename/delete of an existing file stay proposals until a separate,
explicit follow-up - there isn't one built in this project yet).

## What this skill does not do

- It doesn't decide *what* the new text should say - that's the result of
  research/synthesis upstream; this skill only writes it safely once
  you've decided.
- It doesn't touch anything outside the exact section/block/frontmatter
  you targeted, even if the rest of the file looks stale too.
- It doesn't call `obsidian-index-sync` (skill 18, not built) - every
  `applied` result says so on stderr; pass that on rather than implying
  the vault's search index now reflects the change.
