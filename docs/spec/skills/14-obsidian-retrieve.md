# obsidian-retrieve

[Все skills](index.md) · [Основы](../foundation.md) · [Дефолты](../defaults.md) · [User stories](../user-stories.md)

## 3.14. `obsidian-retrieve` — оркестратор hybrid retrieval

**Назначение:** получить минимально достаточный набор кандидатов под задачу, объединяя Omnisearch, terms, RAPTOR, Dataview/Bases и граф.

**Режим `narrow`:** высокая точность, малый top-k, progressive expansion и ранняя остановка после получения достаточного evidence.

**Режим `deep`:** широкий recall, несколько поисковых формулировок, больше MOC/graph expansion, итеративный поиск пробелов и противоречий.

**Обработка:** построить search plan; при возможности выполнить Dataview/Bases pre-filter; запустить нужные retrievers; объединить и дедуплицировать результаты; учесть MOC/graph proximity; оценить стоимость чтения; сформировать `CandidateSet`.

**Выход:** кандидаты, причины отбора, использованные механизмы, итоговое ранжирование, budget usage, рекомендации что раскрывать дальше.

### Связанные разделы

[§3.1 obsidian-search](01-obsidian-search.md) · [§3.11 obsidian-query](11-obsidian-query.md) · [§3.13 obsidian-semantic-search](13-obsidian-semantic-search.md) · [§3.15 obsidian-fragment-reader](15-obsidian-fragment-reader.md). Пользовательские цели: [US-002](../user-stories.md), [US-011](../user-stories.md). Общие проверки: [критерии приёмки](../acceptance.md).
