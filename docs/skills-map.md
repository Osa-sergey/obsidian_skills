# Карта skills

[Индекс 19 паспортов](spec/skills/index.md). Это карта ответственности, а не реестр реализации.

| Skill | Нормативный паспорт | Общие зависимости |
|---|---|---|
| `obsidian-search` | [§3.1](spec/skills/01-obsidian-search.md) | [Общий раздел](spec/foundation.md), [дефолты](spec/defaults.md) |
| `obsidian-context` | [§3.2](spec/skills/02-obsidian-context.md) | [Общий раздел](spec/foundation.md), [дефолты](spec/defaults.md) |
| `obsidian-research` | [§3.3](spec/skills/03-obsidian-research.md) | [Общий раздел](spec/workflows.md), [дефолты](spec/defaults.md) |
| `obsidian-author` | [§3.4](spec/skills/04-obsidian-author.md) | [Общий раздел](spec/data-model.md), [дефолты](spec/defaults.md) |
| `obsidian-revise` | [§3.5](spec/skills/05-obsidian-revise.md) | [Общий раздел](spec/data-model.md), [дефолты](spec/defaults.md) |
| `obsidian-link` | [§3.6](spec/skills/06-obsidian-link.md) | [Общий раздел](spec/foundation.md), [дефолты](spec/defaults.md) |
| `obsidian-metadata` | [§3.7](spec/skills/07-obsidian-metadata.md) | [Общий раздел](spec/data-model.md), [дефолты](spec/defaults.md) |
| `obsidian-moc` | [§3.8](spec/skills/08-obsidian-moc.md) | [Общий раздел](spec/data-model.md), [дефолты](spec/defaults.md) |
| `obsidian-hub` | [§3.9](spec/skills/09-obsidian-hub.md) | [Общий раздел](spec/data-model.md), [дефолты](spec/defaults.md) |
| `obsidian-workflow` | [§3.10](spec/skills/10-obsidian-workflow.md) | [Общий раздел](spec/workflows.md), [дефолты](spec/defaults.md) |
| `obsidian-query` | [§3.11](spec/skills/11-obsidian-query.md) | [Общий раздел](spec/technical-references.md), [дефолты](spec/defaults.md) |
| `obsidian-query-builder` | [§3.12](spec/skills/12-obsidian-query-builder.md) | [Общий раздел](spec/data-model.md), [дефолты](spec/defaults.md) |
| `obsidian-semantic-search` | [§3.13](spec/skills/13-obsidian-semantic-search.md) | [Общий раздел](spec/foundation.md), [дефолты](spec/defaults.md) |
| `obsidian-retrieve` | [§3.14](spec/skills/14-obsidian-retrieve.md) | [Общий раздел](spec/foundation.md), [дефолты](spec/defaults.md) |
| `obsidian-fragment-reader` | [§3.15](spec/skills/15-obsidian-fragment-reader.md) | [Общий раздел](spec/foundation.md), [дефолты](spec/defaults.md) |
| `obsidian-evidence` | [§3.16](spec/skills/16-obsidian-evidence.md) | [Общий раздел](spec/result-formats.md), [дефолты](spec/defaults.md) |
| `obsidian-qa` | [§3.17](spec/skills/17-obsidian-qa.md) | [Общий раздел](spec/workflows.md), [дефолты](spec/defaults.md) |
| `obsidian-index-sync` | [§3.18](spec/skills/18-obsidian-index-sync.md) | [Иерархия RAPTOR](spec/foundation.md), [workflow](spec/workflows.md), [vector payload](spec/data-model.md) |
| `obsidian-gap-search` | [§3.19](spec/skills/19-obsidian-gap-search.md) | [Workflow](spec/workflows.md), [форматы](spec/result-formats.md), [defaults](spec/defaults.md) |

При изменении интерфейса найди всех вызывающих через поиск по репозиторию и проверь downstream путь до результата.
