# Карта модели знаний

| Сущность | Нормативные файлы | Ключевая проверка |
|---|---|---|
| Статья, YAML, links, callouts | [Основа §2.3–2.4](spec/foundation.md), [модель §4](spec/data-model.md), [author](spec/skills/04-obsidian-author.md), [metadata](spec/skills/07-obsidian-metadata.md) | Сохранены неизвестные свойства и ссылка на источник |
| MOC | [Модель §4.2](spec/data-model.md), [moc](spec/skills/08-obsidian-moc.md), [defaults](spec/defaults.md) | `MOC_`, `type: moc`, ракурс, ≤1 основной родитель, отсутствие циклов |
| HUB | [Модель §4.3](spec/data-model.md), [hub](spec/skills/09-obsidian-hub.md), [defaults](spec/defaults.md) | Пара `HUB_*.md/.canvas`, стабильные node IDs и координаты |
| Query registry | [Модель §4.4](spec/data-model.md), [query](spec/skills/11-obsidian-query.md), [builder](spec/skills/12-obsidian-query-builder.md) | `System/Queries/README.md`, параметры, scope, статус исполнения |
| RAPTOR node | [Основа §2.6](spec/foundation.md), [semantic search](spec/skills/13-obsidian-semantic-search.md), [workflow](spec/workflows.md) | Обратимый адрес к Markdown, content hash |
| Vector payload | [Модель](spec/data-model.md), [index sync §3.18](spec/skills/18-obsidian-index-sync.md) | `source` = имя файла, `source_path` = точный путь; удаление по vault + path |
| Имя/суть новой статьи | [Основа §2.5](spec/foundation.md), [author §3.4](spec/skills/04-obsidian-author.md), [модель §4.1](spec/data-model.md) | Уникальное имя с буквенным префиксом при совпадении; `## Суть` из двух предложений |

Структурные отношения в YAML и wikilinks имеют разную семантику. `parent_mocs` — список нулевой или единичной длины; `related_mocs` — поперечные связи. Статья может входить в несколько MOC. Перед изменением схемы проверь свойства vault. См. [ADR-0003](adr/ADR-0003-navigation.md).
