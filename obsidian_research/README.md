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
| 13 | [`obsidian-semantic-search`](skills/obsidian-semantic-search/SKILL.md) | **Implemented** | [§3.13](docs/spec/skills/13-obsidian-semantic-search.md) |
| 14 | [`obsidian-retrieve`](skills/obsidian-retrieve/SKILL.md) | **Implemented** | [§3.14](docs/spec/skills/14-obsidian-retrieve.md) |
| 18 | [`obsidian-index-sync`](skills/obsidian-index-sync/SKILL.md) | **Implemented** | [§3.18](docs/spec/skills/18-obsidian-index-sync.md) |
| 11, 12, 16 | query, query-builder, evidence | Not built | [full list](docs/spec/skills/index.md) |

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

## Semantic search setup (skills 13/14/18)

Skills 13 (`obsidian-semantic-search`), 14 (`obsidian-retrieve`) and 18
(`obsidian-index-sync`) need two external services beyond Omnisearch —
neither is optional-by-code for indexing, though each degrades explicitly
(`embeddings_unavailable`/`vectorstore_unavailable`/extractive-fallback
summaries) rather than silently pretending to work. See
[ADR-0009](docs/adr/ADR-0009-semantic-search-backend.md) for why these two
specifically.

**1. Qdrant** — a long-running Docker container (default `vectorstore.mode:
http` in the vault profile). Start it once:

```bash
mkdir -p ~/.claude/obsidian/qdrant_storage
docker run -d \
  --name obsidian-qdrant \
  -p 6333:6333 -p 6334:6334 \
  -v ~/.claude/obsidian/qdrant_storage:/qdrant/storage \
  --restart unless-stopped \
  qdrant/qdrant:latest

# sanity check
curl -s http://127.0.0.1:6333/ | python3 -m json.tool
```

No Docker available? Set `vectorstore.mode: local` in the vault profile
instead — falls back to an embedded, in-process `QdrantClient(path=...)`,
no server needed, data under `~/.claude/obsidian/index/<vault_id>`.

**2. LM Studio** — a local OpenAI-compatible server (`http://127.0.0.1:1234`
by default) with **two separate models loaded**, since they serve two
different endpoints:

| Model role | Endpoint | Default model name | Used by |
|---|---|---|---|
| Embeddings | `/v1/embeddings` | `qwen3-embedding-0.6b-mlx` | 13/14/18 (required — indexing is skipped without it) |
| Summarizer | `/v1/chat/completions` | `gpt-oss-20b-claude-4.5-sonnet-high-reasoning-distill-mlx` | 18 only (optional — section/article nodes fall back to an extractive stand-in without it, see `summary_source` in the payload) |

Load both from LM Studio's own GUI (Developer → Server tab), not just
`lms load`/`lms ps` — a real operational finding from setting this up: the
CLI can report a model loaded while the HTTP server serving that port still
answers `"No models loaded"` for it. If LM Studio has an API key configured
(its recent-versions default), every request needs
`Authorization: Bearer <token>`.

```bash
# sanity check both models are actually being served (not just "loaded")
export LM_API_TOKEN=sk-...   # only if LM Studio has API key auth on

curl -s http://127.0.0.1:1234/v1/models -H "Authorization: Bearer $LM_API_TOKEN" | python3 -m json.tool

curl -s http://127.0.0.1:1234/v1/embeddings \
  -H "Authorization: Bearer $LM_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"model": "qwen3-embedding-0.6b-mlx", "input": ["ping"]}' | python3 -m json.tool

curl -s http://127.0.0.1:1234/v1/chat/completions \
  -H "Authorization: Bearer $LM_API_TOKEN" -H 'Content-Type: application/json' \
  -d '{"model": "gpt-oss-20b-claude-4.5-sonnet-high-reasoning-distill-mlx", "messages": [{"role":"user","content":"ping"}], "max_tokens": 16}' \
  | python3 -m json.tool
```

**3. Vault profile** — add `embeddings:`/`summarizer:`/`vectorstore:`
sections to `~/.claude/obsidian/vaults/<id>.yaml` (schema:
`lib/obsidian_common/profile.py`'s `EmbeddingsConfig`/`SummarizerConfig`/
`VectorStoreConfig`):

```yaml
embeddings:
  enabled: true
  host: 127.0.0.1
  port: 1234
  model: qwen3-embedding-0.6b-mlx
  api_key: "sk-..."   # blank if LM Studio has no API key configured

summarizer:
  enabled: true        # false = index-sync always uses the extractive fallback
  host: 127.0.0.1
  port: 1234
  model: gpt-oss-20b-claude-4.5-sonnet-high-reasoning-distill-mlx
  api_key: "sk-..."

vectorstore:
  enabled: true
  mode: http            # or "local" for the no-Docker embedded fallback
  host: 127.0.0.1
  port: 6333
  collection_prefix: raptor
```

Once all three are up, a one-off Python check from this project's root
confirms the whole chain before running any of skills 13/14/18:

```bash
python3 -c "
from lib.obsidian_common import profile, embeddings, summarizer, vectorstore as vs
p = profile.load_profile('$HOME/.claude/obsidian/vaults/<id>.yaml')
print('qdrant:    ', vs.ping(p))
print('embeddings:', embeddings.EmbeddingClient(host=p.embeddings.host, port=p.embeddings.port, model=p.embeddings.model, api_key=p.embeddings.api_key).ping())
print('summarizer:', summarizer.LLMSummarizer(host=p.summarizer.host, port=p.summarizer.port, model=p.summarizer.model, api_key=p.summarizer.api_key).ping())
"
```

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

Python 3.9+, `pip install -r requirements.txt` (`pyyaml`, `qdrant-client`
— the latter only for skills 13/14/18, see "Semantic search setup" above).
Every HTTP client in this project (Omnisearch, LM Studio embeddings/
summarizer) uses `urllib` from the standard library on purpose, not a
third-party HTTP/ML library — the S6 fallback (filename/title/alias/H1
matching when Omnisearch is down) is pure Python too. That fallback
intentionally does not also grep full note bodies; it trades recall for
having no extra dependency and says so in its own report
(`omnisearch_unavailable`) rather than pretending to be a full substitute
for a normal run.
