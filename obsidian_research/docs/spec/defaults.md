# Принятые дефолты

[Индекс спецификации](index.md) · [Исторические вопросы](history.md) · [Карта дефолтов](../defaults-map.md)

## 11. Принятые дефолты v0.8

Этот раздел фиксирует рабочую политику первой реализации по ID вопросов. Он имеет приоритет над формулировками «предлагается/уточнить» в исторических разделах 2–8. Любое переопределение указывается в vault profile или явном вызове и не должно нарушать подтверждённые инварианты. Фактические пути, schema, версии плагинов и доступность API определяются при bootstrap на конкретном vault. Указанные лимиты — стартовые значения, которые настраиваются и измеряются.

### G — окружение и область доступа

| ID | Дефолт |
|---|---|
| G1 | Claude Code локально; проектные skills в `.claude/skills/`. Другие среды — будущие адаптеры. |
| G2 | При запуске обнаружить filesystem, Obsidian CLI, Omnisearch HTTP, Dataview API и Bases. Исходный Markdown читать/писать через filesystem; CLI/API — для семантики Obsidian. Не закреплять неподтверждённые версии. |
| G3 | Один активный vault на profile/запуск; несколько vault возможны через отдельные profile, cross-vault retrieval в v1 выключен. Размер определить при bootstrap. |
| G4 | Поддержать Obsidian, Omnisearch, Dataview, Bases, Canvas, CLI; DataviewJS ограниченно, Templater опционален. Отсутствующий компонент обнаружить и обозначить fallback/недоступную функцию. |
| G5 | Читать knowledge-файлы в разрешённом scope, исключая служебные каталоги, trash/cache/git и ненужные бинарные вложения. Автоматическая запись — только в managed folders; явно указанный существующий файл — по команде. |
| G6 | Создание новых draft-статей, MOC/HUB, query-файлов и metadata новых файлов разрешено в managed folders. Существующий prose: сначала proposal/diff, применение по явной команде или в явно выбранном `apply`; generated managed blocks — адресно. |
| G7 | Примеры заметок полезны для style profile, но не блокируют v1; без них использовать шаблоны спецификации. |

### S и C — поиск, граф и чтение

| ID | Дефолт |
|---|---|
| S1 | Приоритет: exact filename → filename без `MOC_`/`HUB_` → YAML `title` → aliases → H1 → текст; filename — канонический поисковый адрес. |
| S2 | `narrow`: сначала name/title/aliases, текст при нехватке; `deep`: name/title/text параллельно. |
| S3 | Контролируемые RU/EN варианты, сокращения, aliases и опечатки; сохранять provenance расширения. |
| S4 | Filters: folder/scope, `type`, `status`, tags, dates; language по умолчанию не hard filter. |
| S5 | Top-5 для narrow и top-20 на lexical query для deep, короткая причина совпадения. |
| S6 | При отказе Omnisearch fallback на term search, filesystem search и RAPTOR; пометка `omnisearch_unavailable`. |
| REQ-RET-0003 | Folder-only query перечисляет все доступные файлы поддерева без текстового запроса; `recursive=true` по умолчанию, `recursive=false` для прямых файлов; без `top-k`-усечения. |
| C1 | Graph depth 1 в narrow, 2 в deep; depth 3 только при обоснованном расширении. |
| C2 | Outlinks и backlinks; структурные YAML-links учитывать, embeds — сильная связь. |
| C3 | Семантических соседей показывать как `discovered_relation`, не как существующий edge. |
| C4 | Narrow ≤12 notes, ≤5 neighbors/node, около 6k retrieved tokens; deep ≤40 notes, ≤10 neighbors/node, около 30k tokens/pass. |
| C5 | Fragment-first; целый файл только при доказанной необходимости, большие вложения сначала индексировать/суммировать. |
| C6 | MOC/HUB включать; daily/archive/system обычно исключать из обхода, если они не названы явно; нерелевантный узел останавливает ветку. |

### R, A и U — исследование и запись

| ID | Дефолт |
|---|---|
| R1 | Narrow — vault-only. Deep — vault и предоставленные/локальные источники; web/repositories при необходимости внешнего или актуального исследования. |
| R2 | Output: synthesis → findings → сравнения/противоречия → gaps → implications → изменения vault. |
| R3 | Приоритет первичным источникам; freshness там, где она важна; код/эксперименты — положительный сигнал, не обязательное условие. |
| R4 | Основания рядом с утверждениями; в deep — внутренний `claim → evidence` map. |
| R5 | Показать конфликт, затем аргументированный синтез с уровнем уверенности. |
| R6 | Research note сохранять при самостоятельной ценности или изменении базы; source-note — для реально использованных внешних источников, нужных повторно. |
| `REQ-RET-0004–0005` | Анализ пробелов запускается по явной задаче (с подсказкой или без неё); scope — целевой HUB/MOC и релевантные соседние материалы в пределах deep budget. План обычно 6–12 неповторяющихся запросов с приоритетом; его подготовка не запускает веб-поиск и не пишет vault. Число запросов сокращать, если пробел закрыт внутренними материалами. |
| A1 | Одна статья — законченная смысловая задача; внутри атомарные абзацы и явные разделы, не дробить механически на множество мелких файлов. |
| A2 | Типы: `concept`, `method`, `guide`, `comparison`, `reference`, `source`, `research`; для новых статей первым разделом тела `## Суть` из двух предложений (`REQ-KNO-0001`), далее structured body → Related → Sources, где применимо. |
| A3 | Основной язык vault/запроса, по умолчанию русский; сохранять технические английские термины, добавлять примеры по пользе. |
| A4 | Человекочитаемые filenames без UUID, варианты терминов через aliases; `MOC_`/`HUB_` обязательны для навигации. При совпадении названий в разных папках использовать согласованный буквенный код проекта после служебного префикса (`REQ-FND-0001`). |
| A5 | При совпадении semantic core обновлять существующую статью; отдельная цель/ракурс/уровень допускают новый файл. |
| A6 | Deep может создать до 5 новых draft articles за проход; сверх лимита — сначала article plan. |
| U1 | Машине structured patch/unified diff, пользователю краткое «что и зачем». |
| U2 | Основания правки: ошибка, новый подтверждённый факт, существенное уточнение, актуализация, практический пример; новая cross-link меняет только link layer. |
| U3 | Существующий prose защищён от автономной перезаписи; managed blocks/структурные поля — адресно; `protected: true` дополнительно учитывается. |
| U4 | Устаревшее заменять в основном тексте; полезную историю — в history callout; противоречия — с attribution. |
| U5 | Merge/split/rename/delete существующих заметок только предлагать до отдельной команды. |
| U6 | Каждая правка имеет change ID; пакетный rollback/review через Git diff, иначе patch manifest. |

### L и M — связи и metadata

| ID | Дефолт |
|---|---|
| L1 | Внутритематические и междоменные связи; необычная междоменная связь требует более сильного evidence. |
| L2 | Controlled vocabulary: `prerequisite`, `clarifies`, `applies`, `example`, `alternative`, `contradicts`, `derived-from` + объяснение. |
| L3 | Главная связь — inline wikilink, вторичные — Related; YAML для структурных relations. |
| L4 | По умолчанию ссылка на статью; heading для конкретного раздела, block link для точного стабильного адреса. |
| L5 | До 5 новых автоматически предложенных links на статью за pass; слабые — suggestions. |
| L6 | Использовать RAPTOR, Omnisearch, terms и graph; broken links обнаруживать и предлагать исправление. |
| M1 | Существующие поля/типы сохранить; расширение schema только additive, конфликт без silent migration. |
| M2 | Types: `concept`, `method`, `guide`, `comparison`, `reference`, `source`, `research`, `moc`, `hub`; status: `draft`, `active`, `review`, `deprecated`, `archived`. |
| M3 | Controlled hierarchical tags на английском; RU/EN variants через aliases/terms. |
| M4 | Core: `type`, `status`, `summary`, `tags`, `created`, `updated`; MOC + perspective/question/terms/parent_mocs; HUB + purpose/route_type/terms/canvas. |
| M5 | Managed notes получают стабильный `uid`; `reviewed` для source/research; difficulty/prerequisites только учебным; глобального note confidence нет. |
| M6 | Первые views: MOC by perspective, child MOCs, orphan articles, drafts/review, stale, recent sources, broken/orphan links, HUB materials, query registry. |

### O и H — навигация

O1 и H1 — уже подтверждённые определения MOC и HUB в §2.4; не считать открытыми вопросами.

| ID | Дефолт |
|---|---|
| O2 | В MOC группы по подтемам/задачам, по этапам только когда естественно для ракурса. |
| O3 | У каждой curated ссылки короткая annotation; required/optional — только для учебного MOC. |
| O4 | Recommended path только когда порядок имеет значение. |
| O5 | Curated static core + dynamic Dataview/Bases blocks; parent, key children и canonical articles — статические. |
| O6 | Обновление после deep research или структурного изменения; нет фоновой записи в v1. |
| O7 | Один основной parent: `parent_mocs` длины 0/1 (корень/дочерний); дополнительные связи в `related_mocs`. Циклы запрещены. |
| O8 | Controlled perspective codes: `theory`, `architecture`, `implementation`, `operations`, `evaluation`, `use-cases` + human question. |
| O9 | Статья в нескольких MOC допустима; дочерний MOC может сменить perspective с явной аннотацией. |
| O10 | Soft limit 4 уровня; child MOC при самостоятельном summary/terms и примерно ≥4 материалах или перегруженном parent. |
| H2 | Материал в любом числе HUB; делить HUB при >7 крупных stages или ~40 карточках. |
| H3 | Один маршрут для технического пользователя; разные novice/expert HUB при реально различной последовательности. |
| H4 | Stage: `goal`, `materials`, `action`, `expected_result`; prerequisites/completion_criteria по необходимости. |
| H6 | Progress tracking выключен; обновление HUB по команде или структурному изменению. |
| H7 | Слева направо; swimlanes только для параллельных ролей/траекторий. |
| H8 | Основной spine + `parallel`, `alternative`, `prerequisite`, `return`. |
| H9 | Сохранять ручные coordinates/IDs, новые nodes добавлять инкрементально; полный relayout по явной команде. |
| H10 | В v1 нативный Obsidian Canvas без обязательного стороннего плагина. |

### W, Q и V — workflow и представления

| ID | Дефолт |
|---|---|
| W1 | Три workflow: narrow QA; deep research + update; reorganize/maintain MOC/HUB/query structure. |
| W2 | `answer` не пишет, `research` создаёт report, `prepare` создаёт drafts/patches, `apply` применяет разрешённое. |
| W3 | Claude выбирает retrieval plan, drafts/links/placement; rename/delete/merge, schema migration и массовая навигация — proposal. |
| W4 | Narrow ~6k tokens/1 pass; deep ~30k/pass и до 2 passes. |
| W5 | Определять изменённые файлы по hash; state вне заметок, например `.claude/obsidian-state/`. Для изменённого файла полностью заменить его векторы через index sync; неизменённые файлы не трогать (`REQ-RET-0001`). |
| W6 | Watchers/automation вне v1; явный запуск. |
| Q1 | Bases — persisted human-facing, Dataview — гибкая runtime query/data access. |
| Q2 | Builder создаёт definitions/views; query skill выполняет и нормализует результаты (§3.11–3.12). |
| Q3 | Existing DataviewJS сначала классифицировать; только data-only можно исполнять, arbitrary rendering/side effects нельзя. |
| Q4 | Первые views: MOC by perspective, child MOCs, orphan articles, drafts/review, stale, HUB stage materials. |
| Q5 | Live result + snapshot; для deep snapshot с timestamp/query/result paths. |
| Q6 | Saved query может подобрать кандидатов HUB; Canvas обновляется только при explicit/structural change с сохранением manual layout. |
| V1 | Engine выбирать автоматически, эквиваленты всех трёх — по запросу. |
| V2 | Reusable definitions в `System/Queries/`: Bases `.base`, DQL documented `.md`, DataviewJS data views `Scripts/`. |
| V3 | Минимум executed result + static preview; `rendered` только при реально открытом Obsidian view. |
| V4 | V1: tables, lists, MOC tree, native Bases cards; tasks/calendar/buttons по необходимости. |
| V5 | Параметры: explicit invocation → current note YAML → saved defaults. |
| V6 | Нативный стиль Obsidian, без custom CSS/components v1. |
| V7 | Существующие definitions исправлять с сохранением смысла; не конвертировать engines молча. |
| V8 | Standalone query проверять в `System/Queries/_sandbox.md` с удалением временного блока; explicit insertion — в target note. |
| V9 | Место по умолчанию `## Dynamic views` перед Related/Sources. |
| V10 | Managed comments со стабильным query ID для обновления блока. |
| V11 | Syntax/context errors исправлять в рамках explicit insertion; изменение логики показывать. Bases обычно отдельный `.base`; inline — для небольшого одноразового view. |

### RAPTOR, лимиты и callouts

| Параметр | Дефолт |
|---|---|
| Embedding/index | `Qwen3-Embedding-0.6B`, 1024 dimensions, cosine; Qdrant local mode как заменяемый адаптер. Смену модели сопровождать миграцией индекса. |
| Unit | Markdown structural node; leaf target 150–350 tokens, hard max ~500, без overlap на естественной границе, при вынужденном split — 1 предложение. |
| Summaries | subsection ~80–150, section ~120–200, article ~150–300 tokens; callout — отдельный leaf с parent heading. |
| Обновление | Incremental **по файлам**: после записи удалить все vectors затронутого файла, заново построить его RAPTOR-иерархию и embeddings; удалённые файлы только очистить. Cross-document clustering выключено в v1 (`REQ-RET-0001–0002`). |
| Vector payload | `source` = filename с расширением, `source_path` = vault-relative путь; плюс vault/node/hash/heading metadata. Точное удаление по vault + path/file UID, не по одному `source`. |
| Narrow | Omnisearch top-5, RAPTOR top-8, merged 8–12, graph depth 1, fragment expansion 3–6, target 4–6k tokens, 1 pass. |
| Deep | Omnisearch top-20, RAPTOR top-25, merged 30–40, graph depth 2, fragment expansion 15–25, target 20–30k tokens/pass, до 2 passes. |
| Early stop | Narrow: все части вопроса имеют прямое основание без существенного обнаруженного конфликта; deep: новый pass не выявляет классов evidence/конфликтов/подтем, меняющих synthesis. Не вводить универсальный vector score threshold. |
| Callouts | Стандартные `[!summary]`, `[!info]`, `[!tip]`, `[!example]`, `[!question]`, `[!warning]`, `[!failure]`, `[!danger]`, `[!quote]`; без зависимости от custom CSS. |

Reusable query сохраняется, если встроен в постоянный MOC/HUB, использован успешно дважды или явно запрошен. `System/Queries/` содержит `README.md`, `Dataview/`, `Bases/`, `Scripts/` и временный `_sandbox.md`. Одноразовый эксперимент каталог не засоряет.
