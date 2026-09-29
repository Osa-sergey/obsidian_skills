---
name: obsidian-metadata
description: Validate, normalize, and safely update the YAML frontmatter of Obsidian notes — checking type/status against the vault's controlled vocabulary, catching near-duplicate tags before they're added (e.g. "RAG" vs "rag" vs "rag-graph"), and merging new fields additively without disturbing anything already there. Use whenever the user wants to add/fix tags or properties, standardize metadata across notes, prepare fields for a Dataview/Bases query, or asks "what type/status should this be" or "am I about to create a duplicate tag". Also consult this before obsidian-author/obsidian-revise write frontmatter that should follow the vault's schema.
---

# obsidian-metadata

Frontmatter (data-model.md §4) has three jobs that are easy to blur
together and shouldn't be: `type`/`status` classify the note, `tags` are
for filtering/search, and neither is a topic list - "similar to X" is not
automatically a tag. Full spec: `docs/spec/skills/07-obsidian-metadata.md`
(US-010); vocabulary and required fields in `M1–M6`,
`docs/spec/defaults.md`. Runs from
`~/.claude/skills/obsidian-metadata/scripts/metadata.py`, and its
`propose`/`apply` are the same safe-write engine `obsidian-revise` uses
(`yaml-merge`), with schema validation run first.

## Check what this vault's schema actually is

```bash
python3 ~/.claude/skills/obsidian-metadata/scripts/metadata.py list-vocab
```

Prints the connected vault's controlled `types`/`statuses`/`link_relations`
and its `managed_folders`/naming config. A vault can override any of these
in its profile (`config/vault_profile.example.yaml` shows the shape) - the
defaults shown are a reasonable starting point, not a universal truth this
skill enforces.

## Validate before (or instead of) changing anything

```bash
python3 ~/.claude/skills/obsidian-metadata/scripts/metadata.py validate --path "notes/Статья.md"
```

Reports missing core fields (`type`, `status`, `tags`, `created`,
`updated` by default - override with `--required`) and any `type`/`status`
outside the controlled vocabulary. **Every issue is a warning, never a
hard failure that blocks anything** - M1 is explicit that an unexpected
existing value gets flagged for a human/Claude to look at, not silently
coerced into the known set or rejected outright. A real vault (especially
one that predates this schema) will have plenty of these; report them,
don't "fix" them without being asked.

## Check a tag before adding it

```bash
python3 ~/.claude/skills/obsidian-metadata/scripts/metadata.py check-tag --tag "GraphRAG"
```

Scans the vault's existing tags for a case/punctuation-only variant
(`graphrag`, `graph-rag`, `graph/rag` would all match) and recommends
reusing it instead - this is what keeps a controlled, hierarchical tag
system (M3) from quietly growing synonyms. No match means it's safe to
propose as genuinely new.

## Propose and apply a metadata update

```bash
echo '{"tags": ["rag/graph"], "status": "review"}' > /tmp/updates.json
python3 ~/.claude/skills/obsidian-metadata/scripts/metadata.py propose --path "notes/Статья.md" \
  --updates-file /tmp/updates.json --reason "normalize schema" --out /tmp/proposal.json
python3 ~/.claude/skills/obsidian-metadata/scripts/metadata.py apply --proposal /tmp/proposal.json
```

`propose` validates the *merged* result and prints warnings before
building the patch, so you see problems before they're written, not after.
The merge itself is additive (`tags`/`aliases`/`topics`/etc. get new items
unioned in, not replaced; any field you don't mention is untouched) and
goes through the same freshness check as `obsidian-revise` - a concurrent
edit to the frontmatter block produces a clean `conflict`, not a silent
overwrite.

## What this skill does not do

- It doesn't invent field values - a missing `type` is reported, not
  guessed at and filled in, unless you explicitly supply one.
- It doesn't migrate or rename an existing field's meaning across the
  vault - M1 requires additive-only schema changes; a real conflict (this
  vault's `status` field means something different than the default
  vocabulary assumes) gets flagged for a human decision, not auto-resolved.
- It doesn't call `obsidian-index-sync` (skill 18, not built) after an
  applied change - say so rather than implying the index is current.
