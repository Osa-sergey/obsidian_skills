# obsidian-qa

[Все skills](index.md) · [Основы](../foundation.md) · [Дефолты](../defaults.md) · [User stories](../user-stories.md)

## 3.17. `obsidian-qa` — narrow QA и insight mining

**Назначение:** отвечать на точные вопросы и извлекать полезные инсайты из vault при минимальном расходе контекста.

**Pipeline:** intent → `obsidian-retrieve(mode=narrow)` → summaries → адресное раскрытие RAPTOR-ветвей → `obsidian-evidence` → answer.

Для insight mining разрешён расширенный вариант narrow-поиска: сопоставление нескольких evidence clusters, поиск повторяющихся паттернов, противоречий и неожиданных связей. Если для вывода требуется широкий обзор темы, skill должен эскалировать задачу в `obsidian-research(mode=deep)`, а не незаметно читать десятки статей.

**Критерий готовности:** ответ трассируется до минимального набора исходных фрагментов; в отчёте можно показать, какие уровни RAPTOR были раскрыты и сколько текста реально прочитано.

### Связанные разделы

[§3.14 obsidian-retrieve](14-obsidian-retrieve.md) · [§3.16 obsidian-evidence](16-obsidian-evidence.md). Пользовательские цели: [US-002](../user-stories.md). Общие проверки: [критерии приёмки](../acceptance.md).
