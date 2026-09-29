#!/usr/bin/env python3
"""obsidian-context: graph context around one or more notes, by depth.

Implements spec passport 02-obsidian-context.md (US-002). Depth is a count
of graph hops (level 0 = the start notes themselves), not folder or heading
depth (foundation.md §... / the passport's "Определение глубины"). This
script only *discovers* the graph and returns addresses + reasons - it does
not read full note bodies (fragment-first, defaults.md block C5); the '##
Суть' preview it attaches per node is explicitly marked as a preview, not a
read, per foundation.md §2.3 rule 2 (обнаруженная vs. прочитанная заметка).

Examples
--------
  context.py --start "zettelkasten/notes/MOC Python.md" --mode deep --direction both
  context.py --start "GraphRAG (Microsoft)" --depth 1 --direction out
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path, PurePosixPath
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import linkgraph, markdown as md  # noqa: E402
from obsidian_common.profile import ProfileError, VaultProfile, resolve_profile  # noqa: E402

DIRECTION_MAP = {"out": "out", "back": "back", "both": "both"}


def resolve_start_notes(profile: VaultProfile, raw_starts: List[str]) -> tuple:
    """Accept a vault-relative path or a bare note title for each --start
    item. Returns (resolved_paths, errors) - an ambiguous title is an error,
    never a silent guess (foundation.md §2.3 rule 6)."""
    basename_index = linkgraph.build_basename_index(profile.vault_path, profile.scope)
    resolved, errors = [], []
    for raw in raw_starts:
        raw = raw.strip()
        if not raw:
            continue
        candidate = raw if raw.endswith(".md") else f"{raw}.md"
        if (profile.vault_path / raw).is_file():
            resolved.append(raw)
            continue
        if (profile.vault_path / candidate).is_file():
            resolved.append(candidate)
            continue
        r = linkgraph.resolve_link_target(profile.vault_path, raw, "", basename_index)
        if r.status == "resolved":
            resolved.append(r.path)
        elif r.status == "ambiguous":
            errors.append({"start": raw, "reason": "ambiguous", "candidates": r.candidates})
        else:
            errors.append({"start": raw, "reason": "not_found"})
    return resolved, errors


def preview_suti(vault_path: Path, rel_path: str) -> str:
    full = Path(vault_path) / rel_path
    if full.suffix.lower() != ".md" or not full.is_file():
        return ""
    raw = md.read_text(full)
    parsed = md.parse_frontmatter(raw)
    headings = md.parse_headings(parsed.body, parsed.body_start_line)
    suti = md.extract_summary_suti(raw, headings)
    if suti:
        return suti
    summary = parsed.meta.get("summary")
    return str(summary) if summary else ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--start", required=True, help="comma-separated paths or note titles")
    ap.add_argument("--mode", default="narrow", choices=["narrow", "deep"])
    ap.add_argument("--depth", type=int, help="override the mode's default graph depth")
    ap.add_argument("--direction", default="both", choices=["out", "back", "both"])
    ap.add_argument("--max-notes", type=int, help="override the mode's default note cap")
    ap.add_argument("--max-neighbors", type=int, help="override the mode's default per-node neighbor cap")
    ap.add_argument("--no-embeds", action="store_true", help="do not follow ![[embeds]] as edges")
    ap.add_argument("--profile", help="profile file path or registered vault id")
    ap.add_argument("--format", default="md", choices=["md", "json"])
    ap.add_argument("--preview", action="store_true", help="attach a cheap '## Суть'/summary preview per node")
    args = ap.parse_args()

    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    limits = profile.limits_for(args.mode)
    depth = args.depth if args.depth is not None else limits.graph_depth
    max_notes = args.max_notes or limits.max_notes
    max_neighbors = args.max_neighbors or limits.max_neighbors

    raw_starts = args.start.split(",")
    start_paths, start_errors = resolve_start_notes(profile, raw_starts)

    if start_errors and not start_paths:
        if args.format == "json":
            print(json.dumps({"start_errors": start_errors}, ensure_ascii=False, indent=2))
        else:
            print("**Не удалось разрешить ни одной исходной заметки:**")
            for e in start_errors:
                if e["reason"] == "ambiguous":
                    print(f"- `{e['start']}` — неоднозначно: {e['candidates']}")
                else:
                    print(f"- `{e['start']}` — не найдено")
        return 2

    result = linkgraph.bfs_context(
        profile.vault_path,
        profile.scope,
        start_paths=start_paths,
        direction=args.direction,
        max_depth=depth,
        max_notes=max_notes,
        max_neighbors=max_neighbors,
        include_embeds=not args.no_embeds,
    )

    nodes_out = []
    for n in result.nodes:
        entry = {
            "path": n.path,
            "depth": n.depth,
            "predecessor": n.predecessor,
            "direction": n.direction,
            "edge_kind": n.edge_kind,
            "anchor": n.anchor,
            "stopped": n.stopped,
            "status": "found",  # discovered, not read - see module docstring
        }
        if args.preview:
            entry["preview"] = preview_suti(profile.vault_path, n.path)
        nodes_out.append(entry)

    payload = {
        "start": start_paths,
        "start_errors": start_errors,
        "mode": args.mode,
        "direction": args.direction,
        "depth": depth,
        "max_notes": max_notes,
        "max_neighbors": max_neighbors,
        "nodes": nodes_out,
        "repeated_edges": result.repeated_edges,
        "broken_links": result.broken_links,
        "truncated_reason": result.truncated_reason,
    }

    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"### Контекст от {start_paths} (mode={args.mode}, depth={depth}, direction={args.direction})\n")
    if start_errors:
        print("⚠️ Часть стартовых заметок не разрешена:")
        for e in start_errors:
            print(f"- `{e['start']}` — {e['reason']} {e.get('candidates', '')}")
        print()
    by_depth = {}
    for n in nodes_out:
        by_depth.setdefault(n["depth"], []).append(n)
    for d in sorted(by_depth):
        print(f"**Уровень {d}:**")
        for n in by_depth[d]:
            pred = f" ← {n['predecessor']} ({n['edge_kind']}, {n['direction']})" if n["predecessor"] else ""
            stop = f" ⛔{n['stopped']}" if n["stopped"] else ""
            print(f"- `{n['path']}`{pred}{stop}")
            if args.preview and n.get("preview"):
                print(f"  > {n['preview'][:200]}")
        print()
    if result.repeated_edges:
        print(f"**Повторные связи (циклы, не перечитаны повторно):** {len(result.repeated_edges)}")
        for e in result.repeated_edges[:10]:
            print(f"- {e['from']} → {e['to']} ({e['kind']}, {e['direction']})")
        print()
    if result.broken_links:
        print(f"**Неразрешённые/битые ссылки, встреченные при обходе:** {len(result.broken_links)}")
        for b in result.broken_links[:10]:
            print(f"- из `{b['from']}` → `{b['target_raw']}` ({b['reason']})")
        print()
    if result.truncated_reason:
        print(f"⚠️ Обход остановлен досрочно: **{result.truncated_reason}**")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
