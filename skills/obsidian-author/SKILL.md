---
name: obsidian-author
description: Turn settled research or a clear new topic into a properly structured new Markdown article in a connected Obsidian vault — with a global-uniqueness name check, the required two-sentence '## Суть' opener, and a draft/active status. Use this whenever the user wants to write up, save, capture, or turn into a note something they just researched or explained; asks to "create a note about X" or "add an article on X" in their vault; or is about to duplicate a topic that might already be covered (this skill checks that first). Only creates brand-new files — for changing an existing article use obsidian-revise instead, and this skill will tell you to if the name already exists.
---

# obsidian-author

Assembles frontmatter + the mandatory `## Суть` opener + a structured body
into a new article, after checking the name is actually unique across the
whole vault. Full spec: `docs/spec/skills/04-obsidian-author.md` (US-004);
defaults `A1–A6` and `REQ-KNO-0001`/`REQ-FND-0001` in `docs/spec/defaults.md`
(paths relative to this project's root). Runs from
`~/.claude/skills/obsidian-author/scripts/author.py` regardless of which
project you're in — see obsidian-search's SKILL.md "Before the first call"
for connecting a project to a vault if that hasn't happened yet.

**Before drafting anything**, check that the topic isn't already covered:
run `obsidian-search` (and `obsidian-context` if a near-miss turns up) —
the spec's placement rule (workflows.md) is explicit that this comes first.
If something close already exists, that's usually `obsidian-revise`'s job,
not a new article.

## 1. Check the name (REQ-FND-0001) — always, before you write a word of body text

```bash
python3 ~/.claude/skills/obsidian-author/scripts/author.py check-name --title "Инкрементальное обновление GraphRAG" \
  --folder "System/drafts" --batch-titles "Другая статья из этого же пакета,Третья"
```

`--batch-titles` catches collisions *within* the set of articles you're
about to create in this same pass, not only against files already in the
vault (A1's "включая пакет одновременно создаваемых файлов"). If it
reports `"unique": false`, apply one of `project_codes_available` from the
vault's profile before the basename (keep it after `MOC_`/`HUB_` if this is
a navigational file, not that this skill creates those - `obsidian-moc`/
`obsidian-hub` do). Never rename an *existing* file to resolve the
collision - that's a separate, explicit decision.

## 2. Pick a skeleton (optional, A2 default section sets)

```bash
python3 ~/.claude/skills/obsidian-author/scripts/author.py skeleton --type concept
```

Types with a built-in skeleton: `concept`, `method`, `comparison`, `guide`,
`reference`, `source`, `research`. These are starting points, not a rigid
template - adapt headings to what the topic actually needs, but keep the
underlying structure rule regardless of type: **one paragraph, one idea**;
headings mark real semantic boundaries (a good one is also where
`obsidian-fragment-reader` would want to stop reading, once that skill
exists); a long section gets subsections before it gets crammed. Use
Obsidian callouts (`> [!summary]`, `[!example]`, `[!warning]`, ...) to
flag a definition/warning/example *inside* an otherwise normal section -
never as a substitute for the section itself.

## 3. Write the body, then assemble

Write the body content (everything *after* `## Суть`) to a scratch file.
The two-sentence gist goes separately as `--suti` - it is not something
you write into the body file:

```bash
python3 ~/.claude/skills/obsidian-author/scripts/author.py new \
  --title "Инкрементальное обновление GraphRAG" --type concept \
  --suti "Инкрементальное обновление GraphRAG изменяет только затронутые узлы и связи графа после появления новых документов. Такой подход сокращает объём пересборки, но требует контроля согласованности индекса и исходных данных." \
  --body-file /tmp/body.md \
  --tags "rag/graph,rag/updates" --topics "[[Topics/GraphRAG]]" --sources "[[Sources/Публикация]]" \
  --moc "[[Maps/MOC_RAG - Индексация]]"
```

Without `--apply` this only **previews** the assembled file (default - it's
a dry run on purpose, matching `generated` vs `written` from the spec's
result vocabulary). Read the preview before adding `--apply`:

```bash
python3 ~/.claude/skills/obsidian-author/scripts/author.py new ... --apply
```

`--folder` defaults to the vault profile's `managed_folders.drafts`
(`System/drafts` unless the vault overrides it) - new articles land in a
skill-owned staging area, not directly inside the user's own PARA/
zettelkasten organization, until they (or `obsidian-moc`) place it.

The script warns, but does not block, if `## Суть` doesn't look like
exactly two sentences (REQ-KNO-0001) - it's a regex heuristic (an
abbreviation or ellipsis can fool it), so treat the warning as "double
check by eye," not as ground truth either way.

## Batches (A6: up to 5 new drafts per deep pass by default)

For a set of articles from one research pass, run `check-name` for all
titles together (via `--batch-titles`) before writing any of them, then
`new` each one. If you're about to propose more than ~5 in one pass,
surface an article plan to the user first instead of writing them all
silently - that cap is a default, not a hard limit, but exceeding it
without saying so isn't.

## What this skill does not do

- It never touches an existing file - `check-name`/`new` on a name that
  already resolves to a real path is a hard stop pointing at
  `obsidian-revise`, not a silent update.
- It doesn't place the new article into a MOC or wire up cross-links
  beyond what you pass via `--topics`/`--sources`/`--moc` on creation -
  that's `obsidian-link`/`obsidian-moc`.
- It doesn't call `obsidian-index-sync` (skill 18, not built in this
  project) - every applied write says so; say the same to the user rather
  than implying search/semantic tools now see the new file.
