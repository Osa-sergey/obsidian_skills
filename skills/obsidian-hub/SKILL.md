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

## What a good HUB looks like

Reference: the hand-made `HUB RAG 2.canvas` in the user's vault. A HUB is
*processed knowledge* ("how does this work and how do I explain it"), not
a list of files - so the canvas must be readable at overview zoom and
useful on zoom-in:

- **Zones → stages → subgroups.** Macro zones (e.g. OFFLINE / ONLINE /
  СКВОЗНЫЕ ТЕМЫ) hold stage groups; a stage may have named subgroups.
- **Every card is a text card: `[[note#heading|alias]]` + one italic line**
  saying what that note gives *at this point of the route*. A bare title
  tells the reader nothing the file name doesn't; `new` warns about cards
  without `desc`. Write the line from the note's actual content (read it
  or its `## Суть`), never from the title alone.
- **Colour = status**, with an auto legend: `new` (green), `stub` (cyan,
  no material yet), `cross` (purple, cross-cutting), `tip` (yellow,
  technique), `warn` (red, risk). Use colours only where they mean something.
- **Labelled arrows**: the spine between stages (`next_label`), plus
  explicit branches and loops (e.g. "несоответствие → правка требований").
- **Control nodes** (an actor or system, e.g. "Заказчик") above/below a zone.

## Creating a HUB

```bash
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py check-name --title "Разработка RAG"
```

`spec.json` (a bare list of stages is also accepted):

```json
{
  "stages": [
    {"id": "req", "zone": "ПОДГОТОВКА", "name": "Постановка задачи",
     "goal": "Определить цель RAG-системы", "action": "собрать требования",
     "expected_result": "список требований", "next_label": "цели → архитектура",
     "cards": [
       {"note": "notes/Требования к RAG.md", "heading": "Метрики", "alias": "Требования",
        "desc": "Как задать метрики качества до выбора модели.", "status": "new"},
       {"text": "Любая пояснительная карточка", "color": "3"}],
     "subgroups": [{"name": "Приёмы", "cards": [{"note": "notes/X.md", "desc": "..."}]}]},
    {"id": "build", "zone": "ПОДГОТОВКА", "name": "Реализация", "goal": "Собрать пайплайн", "cards": []}
  ],
  "controls": [{"id": "owner", "near": "req", "place": "above", "text": "Владелец продукта\nставит цель"}],
  "edges": [{"from": "build", "to": "req", "label": "метрики не достигнуты → пересмотр", "color": "1"}],
  "spine": true
}
```

```bash
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py new \
  --title "Разработка RAG" --purpose "..." --summary "..." \
  --route-type workflow --terms "rag,pipeline" --spec-file spec.json --apply
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py preview \
  --path "Hubs/HUB_Разработка RAG.canvas" --out /tmp/hub.svg
```

- `check-name` checks REQ-FND-0001 uniqueness for **both**
  `HUB_<title>.md` and `.canvas`; a collision on either blocks both.
- Card: `note` (vault path) + optional `heading`, `alias`, `desc`, `status`
  or `color`, `wide`, `id` (so edges can reference it). `{"text": ...}` is a
  plain card. `{"kind": "embed", "file": ...}` is a real Obsidian file node
  (embedded preview) - use sparingly. The older `{"kind": "file", "file"}`
  still works but gives a card with no description.
- Edge `from`/`to` are stage, card, subgroup or control `id`s (a stage's id
  defaults to its name). Sides are chosen from the geometry.
- Stages of one `zone` share a macro group; zones stack top to bottom, a
  zone's stages run left to right and wrap after 4 (or set `row`; set `col`
  to put a stage in a given column - e.g. a loop-back stage right under the
  stage it returns to, so the arrow does not cross other groups).
- `--route-type workflow` (doing something) or `learning` (understanding).
- Without `--apply` this prints the `.md` and counts only. The `.md` is
  generated from the same spec: stage sections with links+descriptions, the
  list of transitions, the colour legend.
- `preview` writes an SVG with the same width model as the layout; clipped
  or overlapping cards are visible there. Open it (or the canvas in
  Obsidian) before calling the HUB done - `validate` cannot judge looks.

## Growing an existing HUB without disturbing its layout

```bash
# One more card below an existing stage
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py add-card \
  --canvas "Hubs/HUB_Разработка RAG.canvas" --stage "Реализация" \
  --note "notes/Новая статья.md" --desc "Что даёт на этом шаге" --status new --apply

# A whole new stage (same shape as one entry of "stages"), wired in after --after
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py add-stage \
  --canvas "Hubs/HUB_Разработка RAG.canvas" --md "Hubs/HUB_Разработка RAG.md" \
  --stage-file new_stage.json [--after "Реализация"] --apply
```

**Neither command moves, resizes, or re-IDs anything already on the
canvas** (H9). `add-card` places the card just below the stage box, under
whatever is already there. `add-stage` places the group right of everything,
at the height of the stage it follows, adds one arrow from that stage and
appends a `### N.` section to the `.md`. A full relayout happens only when
you rebuild with `new` - never as a side effect. `add-stage` is idempotent
by stage name; a repeated `add-card` for the same note stacks a duplicate,
so `validate`/look first.

## Validating a canvas

```bash
python3 ~/.claude/skills/obsidian-hub/scripts/hub.py validate --path "Hubs/HUB_Разработка RAG.canvas"
```

Checks §3.9's list: valid JSON, unique node/edge IDs, every edge endpoint
and file target exists, every `[[link]]` inside a text card resolves (a
`#heading` that is missing is a warning - Obsidian silently opens the top
of the note), no degenerate sizes, no overlapping cards, no card
straddling a group border. `new`/`add-stage` both run this on the result before
writing and refuse to write a canvas with real errors - a warning does
not block.

## What this skill does not do

- It doesn't judge whether the layout *looks* good beyond overlaps and
  borders; use `preview` and Obsidian. Card heights are estimated from text
  length, so a very different font size may clip text.
- It doesn't move a HUB's stages into a different order, split one HUB
  into two, or re-parent anything - those are structural decisions kept
  as explicit, deliberate actions, not a side effect of adding content.
- It doesn't build the topical hierarchy a HUB's stages pull cards from -
  that's `obsidian-moc`; this skill only sequences and displays material
  that already exists.
- It doesn't run `obsidian-index-sync` itself: every applied change prints
  `index_dirty` with the paths - run `obsidian-index-sync` on both halves
  (CLAUDE.md invariant 6) before saying search reflects the HUB.
