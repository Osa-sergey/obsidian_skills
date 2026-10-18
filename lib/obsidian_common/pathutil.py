"""Path/name normalization shared by search, context and research.

Covers three normative rules that every skill needs and none should
re-implement separately:

- REQ-FND-0001 (foundation.md §2.5): global basename uniqueness compares
  Unicode NFC + casefolded basenames, not raw strings.
- foundation.md §2.5: MOC/HUB files must use the `MOC_`/`HUB_` filename
  prefix; a file that merely *looks* like one (e.g. legacy "MOC Python.md"
  with a space, found in real vaults predating this spec) must be flagged
  as a naming-convention conflict, never silently treated as compliant or
  silently renamed (acceptance.md §7 "Найден старый MOC/HUB без префикса").
- scope excludes (foundation.md §2.2): folders like .obsidian/.trash/.git
  are never read or returned as candidates.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable, Optional

from .profile import ScopeConfig, NamingConfig

# Legacy MOC/HUB patterns seen in real vaults that predate the `MOC_`/`HUB_`
# convention: "MOC Foo.md", "MOC - Foo.md", "MOC-Foo.md" (case-insensitive).
_LEGACY_PREFIX_RE = re.compile(r"^(MOC|HUB)[\s\-_]+(?!$)", re.IGNORECASE)


def normalize_rel_path(vault_path: Path, target: Path) -> str:
    """Vault-relative POSIX path, used as the canonical address for a file."""
    target = Path(target)
    if target.is_absolute():
        rel = target.resolve().relative_to(Path(vault_path).resolve())
    else:
        rel = target
    return PurePosixPath(rel.as_posix()).as_posix()


def normalize_basename(name: str) -> str:
    """Unicode NFC + casefold, extension included (REQ-FND-0001)."""
    return unicodedata.normalize("NFC", name).casefold()


def is_excluded(rel_path: str, scope: ScopeConfig) -> bool:
    parts = PurePosixPath(rel_path).parts
    for pattern in scope.exclude:
        pattern_parts = PurePosixPath(pattern).parts
        if parts[: len(pattern_parts)] == pattern_parts:
            return True
        # also match a single path segment anywhere (e.g. exclude "files"
        # wherever it occurs, not only at the vault root)
        if len(pattern_parts) == 1 and pattern_parts[0] in parts:
            return True
    if scope.include:
        included = any(
            parts[: len(PurePosixPath(p).parts)] == PurePosixPath(p).parts
            for p in scope.include
        )
        if not included:
            return True
    return False


@dataclass
class NameClassification:
    kind: Optional[str]  # "moc" | "hub" | None
    compliant: bool  # True if it uses the required prefix exactly
    legacy_pattern: Optional[str]  # e.g. "MOC " if a legacy pattern matched
    stem_without_prefix: str


def classify_navigation_name(basename_no_ext: str, naming: NamingConfig) -> NameClassification:
    """Detect MOC_/HUB_ (compliant) vs. legacy MOC/HUB naming by filename alone.

    This is filename evidence only. foundation.md §2.5 rule 5 is explicit
    that YAML `type` remains the authoritative signal for whether a file
    actually *is* a MOC/HUB; callers must cross-check frontmatter before
    treating a match here as confirmed, not just rely on the name.
    """
    if basename_no_ext.startswith(naming.moc_prefix):
        return NameClassification(
            "moc", True, None, basename_no_ext[len(naming.moc_prefix):]
        )
    if basename_no_ext.startswith(naming.hub_prefix):
        return NameClassification(
            "hub", True, None, basename_no_ext[len(naming.hub_prefix):]
        )
    m = _LEGACY_PREFIX_RE.match(basename_no_ext)
    if m:
        kind = "moc" if m.group(1).upper() == "MOC" else "hub"
        return NameClassification(
            kind, False, m.group(0), basename_no_ext[m.end():]
        )
    return NameClassification(None, False, None, basename_no_ext)


def find_basename_collisions(rel_paths: Iterable[str]) -> dict:
    """Group vault-relative paths by normalized basename.

    Returns {normalized_basename: [rel_path, ...]} restricted to groups with
    more than one entry - the input REQ-FND-0001 needs to disambiguate with a
    project code before creating/renaming a file.
    """
    groups: dict = {}
    for rp in rel_paths:
        base = PurePosixPath(rp).name
        key = normalize_basename(base)
        groups.setdefault(key, []).append(rp)
    return {k: v for k, v in groups.items() if len(v) > 1}
