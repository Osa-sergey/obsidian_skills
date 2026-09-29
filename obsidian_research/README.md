# Obsidian Knowledge Vault Skills

Claude Code skills that turn a connected Obsidian vault into a working
knowledge base: search, graph context, and research, with more to come.
This folder is the whole project — spec, ADRs, and code together. Read
[`CLAUDE.md`](CLAUDE.md) before changing anything here: it governs how the
spec, the code below, and Git history stay in sync, and that process
applies to `skills/`/`lib/`/`bin/` just as much as to `docs/`.

## What's implemented

| # | Skill | Status | Spec passport |
|---:|---|---|---|
| 1 | [`obsidian-search`](skills/obsidian-search/SKILL.md) | **Implemented** | [§3.1](docs/spec/skills/01-obsidian-search.md) |
| 2 | [`obsidian-context`](skills/obsidian-context/SKILL.md) | **Implemented** | [§3.2](docs/spec/skills/02-obsidian-context.md) |
| 3 | [`obsidian-research`](skills/obsidian-research/SKILL.md) | **Implemented** | [§3.3](docs/spec/skills/03-obsidian-research.md) |
| 4 | [`obsidian-author`](skills/obsidian-author/SKILL.md) | **Implemented** | [§3.4](docs/spec/skills/04-obsidian-author.md) |
| 5 | [`obsidian-revise`](skills/obsidian-revise/SKILL.md) | **Implemented** | [§3.5](docs/spec/skills/05-obsidian-revise.md) |
| 6 | [`obsidian-link`](skills/obsidian-link/SKILL.md) | **Implemented** | [§3.6](docs/spec/skills/06-obsidian-link.md) |
| 7 | [`obsidian-metadata`](skills/obsidian-metadata/SKILL.md) | **Implemented** | [§3.7](docs/spec/skills/07-obsidian-metadata.md) |
| 8 | [`obsidian-moc`](skills/obsidian-moc/SKILL.md) | **Implemented** | [§3.8](docs/spec/skills/08-obsidian-moc.md) |
| 9 | [`obsidian-hub`](skills/obsidian-hub/SKILL.md) | **Implemented** | [§3.9](docs/spec/skills/09-obsidian-hub.md) |
| 10 | [`obsidian-workflow`](skills/obsidian-workflow/SKILL.md) | **Implemented** | [§3.10](docs/spec/skills/10-obsidian-workflow.md) |
| 15 | [`obsidian-fragment-reader`](skills/obsidian-fragment-reader/SKILL.md) | **Implemented** | [§3.15](docs/spec/skills/15-obsidian-fragment-reader.md) |
| 17 | [`obsidian-qa`](skills/obsidian-qa/SKILL.md) | **Implemented** | [§3.17](docs/spec/skills/17-obsidian-qa.md) |
| 19 | [`obsidian-gap-search`](skills/obsidian-gap-search/SKILL.md) | **Implemented** | [§3.19](docs/spec/skills/19-obsidian-gap-search.md) |
| 11–14, 16, 18 | query, query-builder, semantic-search, retrieve, evidence, index-sync | Not built | [full list](docs/spec/skills/index.md) |

This table is a snapshot - `python3 skills/obsidian-workflow/scripts/workflow.py list-skills` checks the roster live against what's actually installed, so it can't go stale the way this table can.

"Implemented" means: a `SKILL.md` plus working `scripts/`, tested against a
real vault and a real Omnisearch server. It does not mean every open
question in the passport (`S*`/`C*`/`R*`) is resolved — see each `SKILL.md`
and [`docs/spec/defaults.md`](docs/spec/defaults.md) for what's a settled
default vs. still a judgment call left to Claude at run time.

Skills 1–3 stand on their own (they don't require skills 4–19), but they
also don't have `obsidian-retrieve`/`fragment-reader`/`evidence`/`qa` to
delegate to yet — `obsidian-research`'s `SKILL.md` explains how it covers
that gap itself in the meantime.

## Architecture in one paragraph

Skill code lives here, once, and gets symlinked into `~/.claude/skills/` so
every Claude Code project can use it. Which vault a given project talks to
is a separate, tiny piece of state — a registered vault profile plus a
two-line pointer file in that project — so the same installed skills work
against any number of vaults without editing code. Why: see
[ADR-0008](docs/adr/ADR-0008-skill-distribution.md).

```
skills/<name>/SKILL.md + scripts/   → the skill itself (installed via symlink)
lib/obsidian_common/                → shared parsing/graph/Omnisearch code
bin/obsidian-vault                  → register a vault, connect a project, health-check
config/vault_profile.example.yaml   → documented profile schema
~/.claude/obsidian/vaults/<id>.yaml → an actual registered vault (machine-local, not in git)
<project>/.claude/obsidian-vault.yaml → "this project uses vault <id>" (2 lines)
```

## Quickstart

```bash
# 1. Install the skills for every Claude Code project on this machine
python3 bin/obsidian-vault install-skills

# 2. Register your vault (needs Omnisearch's HTTP server on in its settings)
python3 bin/obsidian-vault register my-vault --path /path/to/vault --port 51361

# 3. Point a project at it (run from inside that other project)
cd /path/to/some/project
python3 /path/to/this/obsidian_research/bin/obsidian-vault connect my-vault

# 4. Sanity check
python3 bin/obsidian-vault doctor my-vault
```

From then on, inside a connected project, Claude can call e.g.
`skills/obsidian-search/scripts/search.py --query "..."` (via the symlinked
skill) with no further setup — it resolves the connected vault on its own.
`bin/obsidian-vault list` shows every registered vault and whether its
Omnisearch server currently answers.

This machine already has `project_live` registered and this folder itself
connected to it (dogfooding this project's own tooling — see the git log).

## Adding skill 4+

Follow the same shape: `skills/<name>/SKILL.md` (frontmatter `name` +
pushy, trigger-focused `description`; imperative body; pointers to
scripts/reference docs) plus `skills/<name>/scripts/*.py` for the
deterministic parts, reusing `lib/obsidian_common` rather than
re-implementing frontmatter/heading parsing or link resolution. Use the
`skill-creator` skill to draft `SKILL.md` and, if useful, to run its
eval/iteration loop. Follow [`CLAUDE.md`](CLAUDE.md)'s process (plan →
implement → update the spec/registry/ADR as needed → verification →
git record) for every change under this folder, code included — this
project is the dogfood case for its own process.

## Requirements

Python 3.9+, `pyyaml`. No other third-party dependencies — the Omnisearch
client uses `urllib` from the standard library on purpose, and the S6
fallback (filename/title/alias/H1 matching when Omnisearch is down) is
pure Python. That fallback intentionally does not also grep full note
bodies; it trades recall for having no extra dependency and says so in its
own report (`omnisearch_unavailable`) rather than pretending to be a full
substitute for a normal run.
