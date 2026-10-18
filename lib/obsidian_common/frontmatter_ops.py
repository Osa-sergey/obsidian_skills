"""Building and validating YAML frontmatter (data-model.md §4).

Used by obsidian-author (new files), obsidian-revise (`yaml-merge` patches)
and obsidian-metadata (validation/normalization). Two hard rules drive this
module's design:

- M1 (defaults.md): schema extension is additive only; an existing field's
  type or value is never silently changed, and unknown fields survive.
- A field ends up quoted/typed the way a human editing this vault by hand
  would expect - list items indented under their key (this vault's own
  notes already look like that; see zettelkasten/notes/*.md), and a
  `[[wikilink]]` value quoted so it round-trips as a string, not YAML flow
  syntax (data-model.md §4.1: "В YAML внутренние ссылки следует заключать
  в кавычки" - confirmed PyYAML already does this automatically for a
  scalar starting with `[`, this module doesn't need to special-case it).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import yaml

# M4 (defaults.md): a sensible, human-familiar key order. Anything not
# listed here keeps whatever order it already had (existing files) or
# falls after these (new files) - this module never reorders a field the
# caller didn't ask it to touch, it only orders the *serialization*.
CORE_KEY_ORDER = [
    "type", "status", "uid",
    "title", "aliases", "summary",
    "tags",
    "topics", "sources", "moc", "hub", "parent_mocs", "related_mocs",
    "perspective", "perspective_question", "terms",
    "purpose", "route_type", "canvas",
    "difficulty", "prerequisites",
    "source_url", "authors", "published", "accessed",
    "reviewed",
    "created", "updated",
]

# M3/M2 defaults - overridable per vault via profile.vocab; these are the
# fallback when a vault's own profile doesn't set `vocab`.
DEFAULT_VOCAB = {
    "types": ["concept", "method", "guide", "comparison", "reference",
              "source", "research", "moc", "hub"],
    "statuses": ["draft", "active", "review", "deprecated", "archived"],
    "link_relations": ["prerequisite", "clarifies", "applies", "example",
                        "alternative", "contradicts", "derived-from"],
}

# M4: core fields expected on every managed note, regardless of type.
CORE_REQUIRED_FIELDS = ["type", "status", "tags", "created", "updated"]

# Fields where a new value is *unioned* into the existing list rather than
# replacing it outright - this is what makes a metadata "update" additive
# by default instead of destructive (M1).
DEFAULT_LIST_UNION_FIELDS = {
    "tags", "aliases", "topics", "sources", "moc", "hub", "related_mocs", "terms",
}


class IndentDumper(yaml.SafeDumper):
    """Indents block-sequence items under their key, matching this vault's
    existing notes (`tags:\\n  - x`) instead of PyYAML's flush-left default
    (`tags:\\n- x`) - both are valid YAML, only one matches what's already
    on disk, and an unnecessary style diff on every touched file would make
    real changes harder to review."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow, False)


def _normalize_for_union(value) -> str:
    return str(value).strip()


def merge_frontmatter(
    existing: Dict, updates: Dict, list_union_fields: Optional[set] = None
) -> Dict:
    """Additive merge: scalars in `updates` overwrite; listed list-fields
    get their new items unioned in (dedup, order-preserving) instead of
    replaced; fields not mentioned in `updates` are untouched. Fields in
    `existing` that `updates` never mentions always survive, including
    ones this module doesn't know about (M1's "unknown field survives")."""
    list_union_fields = (
        DEFAULT_LIST_UNION_FIELDS if list_union_fields is None else list_union_fields
    )
    merged = dict(existing)
    for key, new_value in updates.items():
        if key in list_union_fields and isinstance(new_value, list):
            current = merged.get(key) or []
            if isinstance(current, str):
                current = [current]
            elif not isinstance(current, list):
                current = [current]
            seen = {_normalize_for_union(v) for v in current}
            result = list(current)
            for item in new_value:
                if _normalize_for_union(item) not in seen:
                    result.append(item)
                    seen.add(_normalize_for_union(item))
            merged[key] = result
        else:
            merged[key] = new_value
    return merged


def ordered_items(meta: Dict) -> List[tuple]:
    ordered_keys = [k for k in CORE_KEY_ORDER if k in meta]
    rest = [k for k in meta if k not in ordered_keys]
    return [(k, meta[k]) for k in ordered_keys + rest]


def serialize_frontmatter(meta: Dict) -> str:
    """Returns the full `---\\n...\\n---\\n` block, ready to prepend to a body."""
    ordered = dict(ordered_items(meta))
    dumped = yaml.dump(
        ordered, Dumper=IndentDumper, allow_unicode=True, sort_keys=False,
        default_flow_style=False,
    )
    return f"---\n{dumped}---\n"


@dataclass
class ValidationIssue:
    field: str
    severity: str  # "error" (YAML unparsable / not a mapping) | "warning" (unknown value/missing field)
    message: str


def validate_frontmatter(
    meta: Dict, vocab: Optional[Dict] = None, required_fields: Optional[List[str]] = None
) -> List[ValidationIssue]:
    """Never raises and never mutates `meta` - only reports. `type`/`status`
    outside the controlled vocabulary is a *warning*, not rejected: M1 says
    a conflict gets flagged, not silently forced into the known set (the
    vault's own vocabulary may legitimately differ from these defaults)."""
    vocab = vocab or DEFAULT_VOCAB
    required_fields = required_fields if required_fields is not None else CORE_REQUIRED_FIELDS
    issues: List[ValidationIssue] = []

    for f in required_fields:
        if f not in meta or meta[f] in (None, "", []):
            issues.append(ValidationIssue(f, "warning", f"required field '{f}' is missing"))

    note_type = meta.get("type")
    if note_type is not None and note_type not in vocab.get("types", []):
        issues.append(ValidationIssue(
            "type", "warning",
            f"type={note_type!r} is not in the vault's controlled vocabulary "
            f"({vocab.get('types')}) - not rejected, but check it's intentional",
        ))
    status = meta.get("status")
    if status is not None and status not in vocab.get("statuses", []):
        issues.append(ValidationIssue(
            "status", "warning",
            f"status={status!r} is not in the vault's controlled vocabulary "
            f"({vocab.get('statuses')})",
        ))

    tags = meta.get("tags")
    if tags is not None and not isinstance(tags, list):
        issues.append(ValidationIssue("tags", "warning", "tags should be a list, not a single scalar"))

    return issues


_TAG_HIERARCHY_RE = re.compile(r"^[a-z0-9]+(/[a-z0-9-]+)*$")


def suggest_tag_canonicalization(proposed_tag: str, existing_tags: List[str]) -> Optional[str]:
    """M3: controlled, hierarchical, English tags. Returns an existing tag
    to reuse instead of `proposed_tag` when one is a case/punctuation-only
    variant of it (e.g. 'RAG' vs 'rag', 'rag-graph' vs 'rag/graph') -
    None means no close match was found, propose the new tag as-is."""
    def norm(t: str) -> str:
        return re.sub(r"[\s/_-]+", "", t.strip().lower())

    target = norm(proposed_tag)
    for existing in existing_tags:
        if norm(existing) == target:
            return existing
    return None
