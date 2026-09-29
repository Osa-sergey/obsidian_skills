# Obsidian Knowledge Vault Skills

Claude Code skills that turn a connected Obsidian vault into a working
knowledge base: search, graph context, and research, with more to come.
Full design lives in [`obsidian_research/`](obsidian_research/) — start at
[`obsidian_research/CLAUDE.md`](obsidian_research/CLAUDE.md) before changing
anything here, it governs how this project's spec/code/ADRs stay in sync.

## What's implemented

| # | Skill | Status | Spec passport |
|---:|---|---|---|
| 1 | [`obsidian-search`](skills/obsidian-search/SKILL.md) | **Implemented** | [§3.1](obsidian_research/docs/spec/skills/01-obsidian-search.md) |
| 2 | [`obsidian-context`](skills/obsidian-context/SKILL.md) | **Implemented** | [§3.2](obsidian_research/docs/spec/skills/02-obsidian-context.md) |
| 3 | [`obsidian-research`](skills/obsidian-research/SKILL.md) | **Implemented** | [§3.3](obsidian_research/docs/spec/skills/03-obsidian-research.md) |
| 4–19 | author, revise, link, metadata, moc, hub, workflow, query(-builder), semantic-search, retrieve, fragment-reader, evidence, qa, index-sync, gap-search | Not built | [full list](obsidian_research/docs/spec/skills/index.md) |

"Implemented" means: a `SKILL.md` plus working `scripts/`, tested against a
real vault and a real Omnisearch server. It does not mean every open
question in the passport (`S*`/`C*`/`R*`) is resolved — see each `SKILL.md`
and `obsidian_research/docs/spec/defaults.md` for what's a settled default
vs. still a judgment call left to Claude at run time.

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
[ADR-0008](obsidian_research/docs/adr/ADR-0008-skill-distribution.md).

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

# 3. Point a project at it
cd /path/to/some/project
python3 /path/to/this/repo/bin/obsidian-vault connect my-vault

# 4. Sanity check
python3 /path/to/this/repo/bin/obsidian-vault doctor my-vault
```

From then on, inside that project, Claude can call e.g.
`skills/obsidian-search/scripts/search.py --query "..."` (via the symlinked
skill) with no further setup — it resolves the connected vault on its own.
`bin/obsidian-vault list` shows every registered vault and whether its
Omnisearch server currently answers.

This machine already has `project_live` registered and this repo connected
to it (dogfooding this project's own tooling — see the git log).

## Adding skill 4+

Follow the same shape: `skills/<name>/SKILL.md` (frontmatter `name` +
pushy, trigger-focused `description`; imperative body; pointers to
scripts/reference docs) plus `skills/<name>/scripts/*.py` for the
deterministic parts, reusing `lib/obsidian_common` rather than
re-implementing frontmatter/heading parsing or link resolution. Use the
`skill-creator` skill to draft `SKILL.md` and, if useful, to run its
eval/iteration loop. Follow `obsidian_research/CLAUDE.md`'s process (plan →
implement → update the spec/registry/ADR as needed → verification →
git record) — this repo *is* the dogfood case for `obsidian_research`'s own
process, both directions.

## Requirements

Python 3.9+, `pyyaml`. No other third-party dependencies — the Omnisearch
client uses `urllib` from the standard library on purpose, and the S6
fallback (filename/title/alias/H1 matching when Omnisearch is down) is
pure Python. That fallback intentionally does not also grep full note
bodies; it trades recall for having no extra dependency and says so in its
own report (`omnisearch_unavailable`) rather than pretending to be a full
substitute for a normal run.
