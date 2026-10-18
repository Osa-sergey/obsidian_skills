# Карта retrieval

| Вопрос | Нормативные файлы | Реализация/проверка |
|---|---|---|
| `narrow`/`deep`, RAPTOR | [Основа §2.6–2.7](spec/foundation.md), [semantic search](spec/skills/13-obsidian-semantic-search.md), [retrieve](spec/skills/14-obsidian-retrieve.md), [defaults](spec/defaults.md) | [Алгоритмы](algorithms.md#1-поиск-и-ответ), [ADR-0001](adr/ADR-0001-retrieval.md) |
| Omnisearch, terms, pre-filter, graph | [Search](spec/skills/01-obsidian-search.md), [context](spec/skills/02-obsidian-context.md), [query](spec/skills/11-obsidian-query.md) | [Алгоритмы](algorithms.md#1-поиск-и-ответ) |
| Fragment, callout, provenance | [Reader](spec/skills/15-obsidian-fragment-reader.md), [evidence](spec/skills/16-obsidian-evidence.md), [основа](spec/foundation.md) | [Проверка](verification.md#retrieval-и-ответ) |
| Budget, early stop, fallback | [Дефолты §11](spec/defaults.md), [workflow §8.1](spec/workflows.md) | [Карта дефолтов](defaults-map.md) |
| Актуальность RAPTOR после записи | [Index sync §3.18](spec/skills/18-obsidian-index-sync.md), [vector payload](spec/data-model.md), [defaults](spec/defaults.md) | [ADR-0006](adr/ADR-0006-index-lifecycle.md), [проверка](verification.md#запись-vault-и-актуальность-индекса) |
| Пробелы и внешний поисковый план | [Gap search §3.19](spec/skills/19-obsidian-gap-search.md), [форматы](spec/result-formats.md), [workflow](spec/workflows.md) | [Алгоритм](algorithms.md#6-анализ-пробелов-и-план-внешнего-поиска), [ADR-0007](adr/ADR-0007-gap-search.md) |

Кандидат хранит адрес, метод нахождения и версию источника; evidence возникает только после чтения исходного fragment. Semantic score и MOC-соседство не подтверждают факт.
