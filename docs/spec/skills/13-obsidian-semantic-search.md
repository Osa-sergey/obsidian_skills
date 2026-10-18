# obsidian-semantic-search

[Все skills](index.md) · [Основы](../foundation.md) · [Дефолты](../defaults.md) · [User stories](../user-stories.md)

## 3.13. `obsidian-semantic-search` — RAPTOR semantic retrieval

**Назначение:** искать релевантные материалы по смыслу на нескольких уровнях иерархии, не читая исходные статьи целиком.

**Вход:** query, scope, mode (`narrow|deep`), уровни поиска (`article|section|subsection|chunk|auto`), metadata filters, top-k, token budget.

**Обработка:** сначала искать по summary верхних уровней; при высокой релевантности раскрывать дочерние узлы. Учитывать heading path и границы Markdown. Возвращать score и provenance, но не использовать generated summary как окончательное доказательство факта.

**Выход:** `RaptorMatch[]`: path, heading path, node ID/level, score, summary, line/paragraph range, parent/children, estimated read cost.

**Связь:** точное чтение исходного текста выполняется через `obsidian-fragment-reader`.

**Актуальность индекса:** этот skill только читает индекс, которым после записи управляет [§3.18 `obsidian-index-sync`](18-obsidian-index-sync.md). Если путь помечен `index_dirty`, устаревший embedding не выдаётся за актуальный: использовать исходный Markdown/fallback и обозначить неполноту семантического поиска.

### Связанные разделы

[§3.14 obsidian-retrieve](14-obsidian-retrieve.md) · [§3.15 obsidian-fragment-reader](15-obsidian-fragment-reader.md) · [§3.18 index sync](18-obsidian-index-sync.md). Пользовательские цели: [US-011](../user-stories.md), [US-014](../user-stories.md). Общие проверки: [критерии приёмки](../acceptance.md).
