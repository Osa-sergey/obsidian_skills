# Целевые workflow и placement

[Индекс спецификации](index.md) · [Алгоритмы](../algorithms.md) · [Skill workflow](skills/10-obsidian-workflow.md)

## 8.1. Целевая схема исполнения

### Narrow QA

```text
question
  → obsidian-retrieve(mode=narrow)
      → Dataview/Bases pre-filter when useful
      → Omnisearch / term / RAPTOR
      → fusion + dedup + ranking
  → obsidian-fragment-reader
  → obsidian-evidence
  → obsidian-qa
```

Ожидаемое поведение: ранняя остановка после получения достаточного evidence. Полный `obsidian-research` не запускается.

### Deep research и запись новых знаний

Для задачи поиска пробелов перед внешним исследованием добавить `obsidian-gap-search` после чтения внутренних фрагментов: он принимает подсказку или оценивает HUB/MOC без неё и возвращает план внешних запросов. Если пользователь запросил только план, workflow здесь завершается без записи vault. При запросе на внешнее исследование выбранные запросы передаются `obsidian-research`; найденные результаты проверяются отдельно от гипотез о пробелах (`REQ-RET-0004–0005`).

```text
research question
  → obsidian-retrieve(mode=deep)
  → summaries / MOC / HUB map
  → targeted fragment expansion
  → obsidian-research
  → поиск пробелов и второй retrieval pass при необходимости
  → placement decision:
      existing article → obsidian-revise
      new concept/material → obsidian-author
  → obsidian-link + obsidian-metadata
  → obsidian-moc
  → obsidian-hub only when route/navigation changes
  → obsidian-index-sync(changed paths) after applied writes
```

### Placement decision

Перед созданием новой статьи обязательно проверить:

1. существует ли статья с тем же смысловым ядром;
2. можно ли встроить новый материал как отдельный раздел/подраздел;
3. нужен ли самостоятельный материал из-за другой цели, уровня детализации или ракурса;
4. к каким MOC он относится;
5. изменяет ли он структуру HUB или только содержание существующего узла.

### Требования к реализации RAPTOR-индекса

Индекс обновляется инкрементально по набору изменённых файлов, а внутри каждого изменённого файла выполняется **полная замена** его RAPTOR-узлов и embeddings (`REQ-RET-0001–0002`). После любой применённой записи, включая удаление и rename, обязателен один завершающий вызов [§3.18 `obsidian-index-sync`](skills/18-obsidian-index-sync.md) с фактическим change set. Сначала удаляются все прежние векторы файла, затем для существующего Markdown строится иерархия заголовков и абзацев, для Canvas — маршрута/групп/карточек, для Bases — представлений/полей; для удалённого файла новые векторы не создаются. Прежнее предложение обновлять лишь изменённые leaf nodes здесь заменено. Векторное хранилище не является источником истины: содержимое файлов vault остаётся каноническим.
