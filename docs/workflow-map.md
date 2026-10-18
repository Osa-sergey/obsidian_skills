# Карта workflow

| Путь | Шаги | Нормативные файлы |
|---|---|---|
| Точечный вопрос | `retrieve(narrow)` → reader → evidence → QA | [Workflow §8.1](spec/workflows.md), [retrieve](spec/skills/14-obsidian-retrieve.md), [qa](spec/skills/17-obsidian-qa.md), [defaults](spec/defaults.md) |
| Исследование | `retrieve(deep)` → конфликты/пробелы → research → placement | [Workflow](spec/workflows.md), [research](spec/skills/03-obsidian-research.md), [defaults](spec/defaults.md) |
| Разведка пробелов и запросы в интернет | `retrieve(deep)` → gap search → план запросов; при исследовании → research | [Gap search](spec/skills/19-obsidian-gap-search.md), [форматы](spec/result-formats.md), [ADR-0007](adr/ADR-0007-gap-search.md) |
| Изменение знаний | placement → draft/patch → link/metadata → MOC/HUB → обязательный index sync после записи | [Workflow](spec/workflows.md), [author](spec/skills/04-obsidian-author.md), [revise](spec/skills/05-obsidian-revise.md), [index sync](spec/skills/18-obsidian-index-sync.md) |
| Реорганизация | анализ → proposal/diff → apply → проверка ссылок → index sync | [MOC](spec/skills/08-obsidian-moc.md), [HUB](spec/skills/09-obsidian-hub.md), [оркестратор](spec/skills/10-obsidian-workflow.md), [index sync](spec/skills/18-obsidian-index-sync.md) |
| Запрос/представление | reuse → build → validate → insert/catalog → live/snapshot | [Query](spec/skills/11-obsidian-query.md), [builder](spec/skills/12-obsidian-query-builder.md), [defaults](spec/defaults.md) |

Детали переходов и ошибок: [алгоритмы](algorithms.md). Формат инженерной задачи: [планирование](planning.md). `answer` не пишет, `research` формирует report, `prepare` готовит изменения, `apply` применяет разрешённые правки.
