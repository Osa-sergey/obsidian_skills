"""Shared building blocks for the obsidian-* Claude skills.

This package holds the deterministic, algorithmic pieces that the skills in
../../skills/*/SKILL.md delegate to instead of re-deriving in prose:
vault-profile resolution, path/name normalization, Markdown parsing,
the Omnisearch HTTP client, and the wikilink graph/BFS engine.

Spec reference: docs/spec/foundation.md §2.2 (vault profile)
and docs/adr/ADR-0008-skill-distribution.md (why this lib
is shared rather than duplicated per skill).
"""

__all__ = [
    "profile",
    "pathutil",
    "markdown",
    "omnisearch",
    "linkgraph",
]
