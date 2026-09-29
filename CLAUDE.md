# Obsidian Knowledge Vault Skills — repo guide

This repo has two halves that follow different rules:

- **`obsidian_research/`** — the modular specification (19 skill passports,
  data model, algorithms, ADRs, requirement registry). It has its own
  process doc: **read [`obsidian_research/CLAUDE.md`](obsidian_research/CLAUDE.md)
  before changing spec, code, or process** — it governs how requirements
  get IDs, when an ADR is needed, and how a change gets recorded in Git.
  Treat it as normative for *any* change under `skills/`, `lib/`, `bin/`,
  or `config/` too, not just for edits inside `obsidian_research/` itself.
- **`skills/`, `lib/`, `bin/`, `config/`** — the actual implementation.
  [`README.md`](README.md) has the quickstart and current implementation
  status; [`ADR-0008`](obsidian_research/docs/adr/ADR-0008-skill-distribution.md)
  explains why skills install at user level and vaults connect via a
  profile registry rather than per-project copies.

## Quick orientation

- Implementing or changing a skill: read that skill's spec passport under
  `obsidian_research/docs/spec/skills/`, its `defaults.md` block, and its
  current `skills/<name>/SKILL.md` — in that order.
- Shared algorithmic code (frontmatter/heading parsing, wikilink
  resolution, graph BFS, the Omnisearch client) lives in
  `lib/obsidian_common/` — extend it there rather than duplicating logic
  inside a skill's own `scripts/`.
- Use the `skill-creator` skill when drafting or revising a `SKILL.md` —
  it has the authoring conventions (progressive disclosure, description
  writing, scripts/references/assets split) this project follows.
- This machine has vault `project_live` registered and this repo connected
  to it already (`.claude/obsidian-vault.yaml`, gitignored — machine-local
  state, see ADR-0008). Re-run `bin/obsidian-vault list`/`doctor` if a
  script reports no profile or an unreachable Omnisearch server.
