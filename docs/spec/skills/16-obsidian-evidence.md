# obsidian-evidence

[Все skills](index.md) · [Основы](../foundation.md) · [Дефолты](../defaults.md) · [User stories](../user-stories.md)

## 3.16. `obsidian-evidence` — точные выдержки и основания

**Назначение:** превратить CandidateSet в минимальный набор исходных фрагментов, достаточный для конкретных утверждений.

**Обработка:** запросить через fragment-reader исходные passages; объединить дубли; отделить прямое подтверждение от интерпретации; при необходимости запросить один дополнительный соседний/дочерний фрагмент.

**Выход:** `EvidenceItem`: claim/question facet, file, heading path, fragment, paraphrase/short quote, directness, retrieval methods, confidence, read cost.

### Связанные разделы

[§3.15 obsidian-fragment-reader](15-obsidian-fragment-reader.md) · [§3.17 obsidian-qa](17-obsidian-qa.md). Пользовательские цели: [US-002](../user-stories.md), [US-003](../user-stories.md). Общие проверки: [критерии приёмки](../acceptance.md).
