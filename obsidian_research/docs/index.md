# Карта документации

## Начало работы

1. [CLAUDE.md](../CLAUDE.md) — короткие правила работы над проектом.
2. [Спецификация v0.9.0](spec/index.md) — вход в модульные нормативные разделы, включая [19 файлов skills](spec/skills/index.md) и [дефолты](spec/defaults.md).
3. [User stories](spec/user-stories.md) — понять пользовательскую цель; [правила ID](spec/structure.md) и [реестр](spec/requirements-registry.md) — добавлять новые требования.
4. [Карта skills](skills-map.md) — найти паспорт и зависимости.
5. [Карта retrieval](retrieval-map.md) и [модель данных](data-model-map.md) — общие зависимости.
6. [Алгоритмы](algorithms.md) — последовательность действий между skills и проверяемые состояния.
7. [Планирование](planning.md), [проверка](verification.md) и [Git-запись](git-change-record.md) — провести изменение от требования до зафиксированного результата.
8. [Дефолты](defaults-map.md) — краткий указатель к нормативному [§11](spec/defaults.md).
9. [Индекс ADR](adr/index.md) — причины архитектурных решений и порядок их пересмотра.

## Источники и приоритет

Явное новое требование пользователя → нормативный файл спецификации → действующие ADR (для объяснения архитектуры) → алгоритмы/карты. ADR описывает выбор, но не отменяет новую норму спецификации; противоречие исправляют в той же задаче. [Архив единого файла v0.7](spec/Obsidian_Claude_Skills_Spec_v0.7-archive.md) хранится для сверки переноса. Численные значения — стартовые настройки, а не обещание, что пользовательский vault/плагины проверены.

## Быстрый маршрут

| Задача | Читать |
|---|---|
| Пробелы темы и запросы для интернета | [Gap search](spec/skills/19-obsidian-gap-search.md), [алгоритм](algorithms.md#6-анализ-пробелов-и-план-внешнего-поиска), [форматы](spec/result-formats.md), [ADR-0007](adr/ADR-0007-gap-search.md) |
| Поиск и ответ | [Основа](spec/foundation.md), [retrieval skills](spec/skills/index.md), [workflow](spec/workflows.md), [defaults](spec/defaults.md), [карта retrieval](retrieval-map.md) |
| Исследование и обновление заметок | [Паспорта](spec/skills/index.md), [workflow](spec/workflows.md), [план](planning.md), [проверка](verification.md) |
| MOC/HUB и метаданные | [Общая модель](spec/foundation.md), [паспорта](spec/skills/index.md), [модель данных](spec/data-model.md), [карта](data-model-map.md) |
| Dataview/Bases/DataviewJS | [Query skills](spec/skills/index.md), [CLI](spec/technical-references.md), [алгоритмы](algorithms.md) |
| Запись vault и актуальность поиска | [Index sync](spec/skills/18-obsidian-index-sync.md), [алгоритм](algorithms.md#2-индексация-markdown-и-fragment-reader), [ADR-0006](adr/ADR-0006-index-lifecycle.md) |
| Новое решение | [Шаблон ADR](adr/template.md), [индекс](adr/index.md), соответствующий нормативный файл |
| Новая функция/требование | [user stories](spec/user-stories.md), [правила кодов](spec/structure.md), [реестр](spec/requirements-registry.md), [план](planning.md) |

Старые номера §1–12 сохранены внутри файлов. Соответствие номера и файла — в [индексе спецификации](spec/index.md); при недоступном якоре ищи точный номер/ID в нужном файле.
