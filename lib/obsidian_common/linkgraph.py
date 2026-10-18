"""Vault-wide filesystem walk, wikilink resolution and the context BFS.

Backs obsidian-context (skill 02) directly and obsidian-search's folder
listing mode (REQ-RET-0003). Kept independent of Omnisearch on purpose:
foundation.md §3.1 says folder listing "не зависит от ранжирования
Omnisearch" - this module never calls the network.

Link resolution mirrors how Obsidian itself resolves a bare `[[Note Name]]`
(shortest matching path wins) but - unlike Obsidian's UI - never resolves
silently when more than one file shares a basename: it reports the match as
ambiguous with every candidate, because foundation.md §2.3 rule 6 requires
exactly that ("Совпадение имён в разных папках и алиасы требуют проверки").
"""
from __future__ import annotations

import os
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Dict, Iterator, List, Optional

from . import markdown as md
from .pathutil import is_excluded, normalize_basename
from .profile import ScopeConfig

TEXT_EXTENSIONS = {".md", ".canvas", ".base"}


def iter_vault_files(
    vault_path: Path, scope: ScopeConfig, extensions: Optional[set] = None
) -> Iterator[str]:
    vault_path = Path(vault_path)
    for root, dirs, files in os.walk(vault_path):
        rel_root = PurePosixPath(Path(root).relative_to(vault_path).as_posix())
        # prune excluded directories in place so os.walk does not descend
        pruned = []
        for d in dirs:
            rel_dir = (rel_root / d).as_posix() if str(rel_root) != "." else d
            if not is_excluded(rel_dir, scope):
                pruned.append(d)
        dirs[:] = pruned
        for f in files:
            rel_file = (rel_root / f).as_posix() if str(rel_root) != "." else f
            if is_excluded(rel_file, scope):
                continue
            if extensions and Path(f).suffix.lower() not in extensions:
                continue
            yield rel_file


def build_basename_index(vault_path: Path, scope: ScopeConfig) -> Dict[str, List[str]]:
    """normalized stem (no extension) -> [vault-relative .md paths]."""
    index: Dict[str, List[str]] = {}
    for rel in iter_vault_files(vault_path, scope, extensions={".md"}):
        stem = PurePosixPath(rel).stem
        key = normalize_basename(stem)
        index.setdefault(key, []).append(rel)
    return index


@dataclass
class ResolvedTarget:
    status: str  # resolved | ambiguous | not_found
    path: Optional[str]
    candidates: List[str] = field(default_factory=list)


def resolve_link_target(
    vault_path: Path,
    link_target: str,
    source_rel_path: str,
    basename_index: Dict[str, List[str]],
) -> ResolvedTarget:
    vault_path = Path(vault_path)
    raw = link_target.strip()
    if not raw:
        # [[#Heading]] / [[#^blockid]]: no note name before '#' means "this
        # same file" in Obsidian, not an unresolved/missing target.
        if not source_rel_path:
            return ResolvedTarget("not_found", None)
        return ResolvedTarget("resolved", source_rel_path)

    # 1. explicit path (contains a folder separator)
    if "/" in raw:
        for candidate in (raw, f"{raw}.md"):
            if (vault_path / candidate).is_file():
                return ResolvedTarget("resolved", PurePosixPath(candidate).as_posix())

    # 2. same folder as the source note
    source_dir = PurePosixPath(source_rel_path).parent
    same_dir_candidate = (
        (source_dir / raw).as_posix() if str(source_dir) != "." else raw
    )
    for candidate in (same_dir_candidate, f"{same_dir_candidate}.md"):
        if (vault_path / candidate).is_file():
            return ResolvedTarget("resolved", PurePosixPath(candidate).as_posix())

    # 3. basename index (Obsidian's normal case: a bare note title)
    stem = PurePosixPath(raw).stem if raw.lower().endswith(".md") else raw
    key = normalize_basename(stem)
    matches = basename_index.get(key, [])
    if len(matches) == 1:
        return ResolvedTarget("resolved", matches[0])
    if len(matches) > 1:
        # Obsidian itself prefers the shortest path silently; we still
        # surface every candidate so callers can flag the ambiguity.
        ranked = sorted(matches, key=lambda p: (p.count("/"), p))
        return ResolvedTarget("ambiguous", ranked[0], candidates=ranked)
    return ResolvedTarget("not_found", None)


@dataclass
class LinkEdge:
    source: str
    target: Optional[str]  # resolved vault-relative path, or None if unresolved
    target_raw: str
    kind: str  # wikilink | embed | frontmatter:<field>
    anchor: Optional[str]
    ambiguous_candidates: List[str] = field(default_factory=list)


def extract_edges_from_file(
    vault_path: Path, rel_path: str, basename_index: Dict[str, List[str]]
) -> List[LinkEdge]:
    full_path = Path(vault_path) / rel_path
    raw = md.read_text(full_path)
    parsed = md.parse_frontmatter(raw)
    edges: List[LinkEdge] = []

    for link in md.extract_wikilinks(parsed.body):
        resolved = resolve_link_target(vault_path, link.target, rel_path, basename_index)
        edges.append(
            LinkEdge(
                source=rel_path,
                target=resolved.path,
                target_raw=link.target,
                kind="embed" if link.is_embed else "wikilink",
                anchor=link.anchor,
                ambiguous_candidates=resolved.candidates
                if resolved.status == "ambiguous"
                else [],
            )
        )
    for fl in md.extract_frontmatter_links(parsed.meta):
        resolved = resolve_link_target(vault_path, fl.target, rel_path, basename_index)
        edges.append(
            LinkEdge(
                source=rel_path,
                target=resolved.path,
                target_raw=fl.target,
                kind=f"frontmatter:{fl.field}",
                anchor=fl.anchor,
                ambiguous_candidates=resolved.candidates
                if resolved.status == "ambiguous"
                else [],
            )
        )
    return edges


def build_forward_index(
    vault_path: Path, scope: ScopeConfig, basename_index: Dict[str, List[str]]
) -> Dict[str, List[LinkEdge]]:
    index: Dict[str, List[LinkEdge]] = {}
    for rel in iter_vault_files(vault_path, scope, extensions={".md"}):
        try:
            index[rel] = extract_edges_from_file(vault_path, rel, basename_index)
        except (OSError, UnicodeDecodeError):
            index[rel] = []
    return index


def build_backward_index(
    forward: Dict[str, List[LinkEdge]]
) -> Dict[str, List[LinkEdge]]:
    backward: Dict[str, List[LinkEdge]] = {}
    for source, edges in forward.items():
        for edge in edges:
            if edge.target is None:
                continue
            backward.setdefault(edge.target, []).append(edge)
    return backward


@dataclass
class ContextNode:
    path: str
    depth: int
    predecessor: Optional[str]
    direction: Optional[str]  # outlink | backlink | start
    edge_kind: Optional[str]
    anchor: Optional[str]
    stopped: Optional[str] = None  # reason expansion did not continue, if any


@dataclass
class BFSResult:
    nodes: List[ContextNode]
    repeated_edges: List[dict]
    truncated_reason: Optional[str]
    broken_links: List[dict]


def _traversal_blocked(rel_path: str, traversal_exclude: List[str]) -> bool:
    parts = PurePosixPath(rel_path).parts
    return any(seg in traversal_exclude for seg in parts[:-1])


def bfs_context(
    vault_path: Path,
    scope: ScopeConfig,
    start_paths: List[str],
    direction: str,
    max_depth: int,
    max_notes: int,
    max_neighbors: int,
    include_embeds: bool = True,
) -> BFSResult:
    if direction not in ("out", "back", "both"):
        raise ValueError("direction must be 'out', 'back' or 'both'")

    basename_index = build_basename_index(vault_path, scope)
    forward = build_forward_index(vault_path, scope, basename_index)
    backward = build_backward_index(forward) if direction in ("back", "both") else {}

    visited: Dict[str, ContextNode] = {}
    order: List[ContextNode] = []
    repeated_edges: List[dict] = []
    broken_links: List[dict] = []
    truncated_reason = None

    queue = deque(
        (p, 0, None, "start", None, None) for p in start_paths
    )
    queued_or_visited = set(start_paths)

    while queue:
        path, depth, pred, dirn, kind, anchor = queue.popleft()

        if path in visited:
            if pred is not None:
                repeated_edges.append(
                    {"from": pred, "to": path, "kind": kind, "direction": dirn}
                )
            continue
        if len(visited) >= max_notes:
            truncated_reason = "max_notes_reached"
            break

        node = ContextNode(path, depth, pred, dirn if dirn != "start" else None, kind, anchor)
        visited[path] = node
        order.append(node)

        if depth >= max_depth:
            continue
        # a start note is always expanded even if it lives in an excluded
        # traversal folder; anything reached *from* one is not (C6 default)
        if depth > 0 and _traversal_blocked(path, scope.traversal_exclude):
            node.stopped = "traversal_excluded_folder"
            continue
        if not Path(vault_path, path).is_file():
            node.stopped = "source_file_missing"
            continue

        neighbors = []
        if direction in ("out", "both"):
            for edge in forward.get(path, []):
                if edge.kind == "embed" and not include_embeds:
                    continue
                neighbors.append((edge, "outlink"))
        if direction in ("back", "both"):
            for edge in backward.get(path, []):
                neighbors.append((edge, "backlink"))

        capped = neighbors[:max_neighbors]
        if len(neighbors) > max_neighbors:
            node.stopped = f"max_neighbors_reached({len(neighbors)} found)"

        for edge, dirn2 in capped:
            if edge.target is None:
                broken_links.append(
                    {
                        "from": path,
                        "target_raw": edge.target_raw,
                        "kind": edge.kind,
                        "reason": "ambiguous" if edge.ambiguous_candidates else "not_found",
                        "candidates": edge.ambiguous_candidates,
                    }
                )
                continue
            target = edge.target if dirn2 == "outlink" else edge.source
            if target == path:
                continue  # self-link
            if target not in queued_or_visited and len(queued_or_visited) >= max_notes:
                truncated_reason = "max_notes_reached"
                continue
            queued_or_visited.add(target)
            queue.append((target, depth + 1, path, dirn2, edge.kind, edge.anchor))

    return BFSResult(order, repeated_edges, truncated_reason, broken_links)
