---
name: obsidian-hub
description: Create and grow a HUB — the mandatory Markdown + Canvas pair that shows a visual work or learning route across stages, each pulling in MOCs and articles. Use whenever the user wants a step-by-step route/roadmap/onboarding path through a topic, a visual overview of a multi-stage process, or asks to see "the big picture" of how materials fit into a workflow. Not for a plain topical map with no sequence or stages — that's obsidian-moc. Also use it to add a stage or a card into an existing HUB without disturbing its current manual layout.
---

# obsidian-hub

A HUB is a *route*, not a map: existence in a HUB means "this belongs at
this point in a sequence," not "this is part of this topic" (that's what
a MOC already says). Every HUB is a paired `HUB_<Title>.md` (searchable,
Dataview-friendly description) and `HUB_<Title>.canvas` (the visual
route) with the same stem - never one without the other. Full spec:
`docs/spec/skills/09-obsidian-hub.md` (US-008); ADR-0003 explains the
paired-file design. Runs from `~/.claude/skills/obsidian-hub/scripts/hub.py`.

## Creating a HUB

```bash
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py check-name --title "Разработка RAG"
```

`stages.json` (one object per stage, in the order they should appear -
H4's default fields):

```json
[
  {"name": "Постановка задачи", "goal": "Определить цель RAG-системы",
   "materials": ["чеклист требований"],
   "cards": [{"kind": "file", "file": "notes/Требования к RAG.md"}]},
  {"name": "Реализация", "goal": "Собрать пайплайн", "action": "написать и протестировать код",
   "expected_result": "рабочий прототип",
   "cards": [{"kind": "file", "file": "Maps/MOC_RAG - Индексация.md"},
             {"kind": "text", "text": "Легенда: жёлтый = обязательный этап"}]}
]
```

```bash
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py new \
  --title "Разработка RAG" --purpose "Пройти путь от задачи до продакшена" \
  --summary "Маршрут разработки RAG-системы от постановки задачи до эксплуатации." \
  --route-type workflow --terms "rag,pipeline" --stages-file stages.json --apply
```

- `check-name` checks REQ-FND-0001 uniqueness for **both** `HUB_<title>.md`
  and `HUB_<title>.canvas` together - a collision on either half blocks
  both; apply the same project-code prefix to both if one is needed.
- A `cards` entry can be `"kind": "file"` (a MOC or article - reference
  it, never copy its content in) or `"kind": "text"` (a short legend/
  explanation card with no linked file). `subpath` on a file card (e.g.
  `"#Механизм"`) anchors it to a specific section.
- `--route-type workflow` (doing something) or `learning` (understanding
  something) - the only two values (H5/route_type default).
- Stages lay out left to right automatically (H7 default): one visual
  group per stage, a goal blurb at the top, cards stacked below, and a
  sequential "next" edge between consecutive stages (H8's default main
  spine). Without `--apply` this only previews both files' content.

## Growing an existing HUB without disturbing its layout

```bash
# One more card in an existing stage
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py add-card \
  --canvas "Hubs/HUB_Разработка RAG.canvas" --stage "Реализация" --file "notes/Новая статья.md" --apply

# A whole new stage, added to the .canvas AND appended to the paired .md
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py add-stage \
  --canvas "Hubs/HUB_Разработка RAG.canvas" --md "Hubs/HUB_Разработка RAG.md" \
  --stage-file new_stage.json --apply
```

**Neither command ever moves, resizes, or re-IDs anything already on the
canvas** (H9: preserve manual coordinates and cards). `add-card` places
the new card just below the target stage's box, stacked under whatever is
already there (including a previous `add-card` call) so nothing overlaps.
`add-stage` places the new stage group to the right of the rightmost
existing one and wires a single "next" edge in from it - a full visual
relayout only happens if you explicitly rebuild the canvas from scratch
with `new`, never as a side effect of adding one thing.

Both are idempotent: re-running `add-stage` with a stage of the same
`name` reports it already exists rather than creating a duplicate group
and a duplicate `### N.` section; a repeated `add-card` for the exact
same file just stacks a redundant card today - check the canvas first
(`validate`, below) if you're not sure something's already there.

## Validating a canvas

```bash
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py validate --path "Hubs/HUB_Разработка RAG.canvas"
```

Checks §3.9's list: valid JSON, unique node/edge IDs, every edge endpoint
and every file-card target actually exists, no degenerate (zero/negative)
sizes, and flags two nodes sharing identical geometry as a likely copy-
paste mistake. `new`/`add-stage` both run this on the result before
writing and refuse to write a canvas with real errors - a warning does
not block.

## What this skill does not do

- It doesn't verify the layout *looks* good - only that it's structurally
  valid. Open it in Obsidian to actually eyeball spacing and overlaps
  (the passport calls this out explicitly as needing visual review).
- It doesn't move a HUB's stages into a different order, split one HUB
  into two, or re-parent anything - those are structural decisions kept
  as explicit, deliberate actions, not a side effect of adding content.
- It doesn't build the topical hierarchy a HUB's stages pull cards from -
  that's `obsidian-moc`; this skill only sequences and displays material
  that already exists.
- It doesn't call `obsidian-index-sync` (skill 18, not built) after a
  write - every applied change says so; say the same rather than implying
  the vault's search index reflects either half of the pair yet.
