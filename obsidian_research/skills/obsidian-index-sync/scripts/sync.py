#!/usr/bin/env python3
"""obsidian-index-sync: keep the RAPTOR/Qdrant index in sync with the
vault's real files - full replacement per changed file (ADR-0006), never
a diff of individual nodes.

Implements spec passport 18-obsidian-index-sync.md (US-014), ADR-0006,
ADR-0009. The actual chunk -> summarize -> embed -> store pipeline lives
in lib/obsidian_common/indexing.py; this script is the CLI surface plus
title-to-path resolution for the selective resync mode.

Subcommands
-----------
  resync        - full rebuild for one or more explicit vault-relative
                  paths (created/modified case). Old vectors for each
                  path are deleted first, then the file is re-read,
                  re-chunked, re-summarized and re-embedded from scratch.
  resync-titles - same as resync, but takes article *names* instead of
                  paths (the user-requested "update the index for only
                  these articles" mode) - resolves each name against
                  filename/YAML title/aliases before indexing. Ambiguous
                  or unresolved names are reported, never guessed.
  delete        - one or more paths were removed from the vault - deletes
                  their vectors, never reads or rebuilds (spec step 3).
  rename        - old path's vectors are deleted, then the file is
                  indexed fresh at its new path.
  full          - walk the whole vault (respecting scope excludes) and
                  resync every indexable file. Markdown only for now -
                  .canvas/.base indexing is spec'd (step 4) but not yet
                  implemented here, see the "not yet built" note in the
                  full-sync output.
  status        - how many vectors currently exist for each given path,
                  without touching anything - a quick way to check
                  whether a file is actually indexed before trusting
                  semantic search results for it.

Every subcommand reports one IndexSyncResult-shaped record per file, with
an honest `status` (`indexed|deleted|not_indexable|index_dirty`) - never
"ok" as a blanket result for a batch where some files failed.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import indexing, linkgraph, markdown as md  # noqa: E402
from obsidian_common.pathutil import is_excluded, normalize_basename  # noqa: E402
from obsidian_common.profile import ProfileError, VaultProfile, resolve_profile  # noqa: E402
from obsidian_common import vectorstore as vs  # noqa: E402

INDEXABLE_EXTENSIONS = {".md"}  # .canvas/.base per spec step 4 - not yet implemented


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).strip().casefold()


def _result_dict(r: indexing.IndexFileResult) -> dict:
    return {
        "source_path": r.source_path,
        "status": r.status,
        "nodes_written": r.nodes_written,
        "nodes_deleted_first": r.nodes_deleted_first,
        "summary_fallback_nodes": r.summary_fallback_nodes,
        "dimension": r.dimension,
        "error": r.error,
    }


def _print_results(results: List[indexing.IndexFileResult], fmt: str) -> int:
    any_dirty = any(r.status == "index_dirty" for r in results)
    if fmt == "json":
        print(json.dumps({
            "results": [_result_dict(r) for r in results],
            "index_dirty": any_dirty,
        }, ensure_ascii=False, indent=2))
        return 1 if any_dirty else 0
    for r in results:
        line = f"{r.status:14s} {r.source_path}"
        if r.status == "indexed":
            line += f"  ({r.nodes_written} nodes"
            if r.summary_fallback_nodes:
                line += f", {len(r.summary_fallback_nodes)} used extractive fallback"
            line += ")"
        if r.error:
            line += f"  ERROR: {r.error}"
        print(line)
    if any_dirty:
        print("\n⚠️ index_dirty for one or more files - search results for them may be "
              "incomplete or stale until this is retried successfully.")
    return 1 if any_dirty else 0


def cmd_resync(args, profile: VaultProfile) -> int:
    results = []
    for rel_path in args.paths:
        full = Path(profile.vault_path) / rel_path
        if not full.is_file():
            results.append(indexing.IndexFileResult(rel_path, "not_indexable", error="file not found in vault"))
            continue
        if Path(rel_path).suffix.lower() not in INDEXABLE_EXTENSIONS:
            results.append(indexing.IndexFileResult(
                rel_path, "not_indexable",
                error=f"extension {Path(rel_path).suffix!r} not indexable yet (only .md)",
            ))
            continue
        raw = md.read_text(full)
        results.append(indexing.index_file(profile, rel_path, raw))
    return _print_results(results, args.format)


def _resolve_titles(profile: VaultProfile, names: List[str]) -> Dict[str, List[str]]:
    """name -> list of matching vault-relative .md paths (0 = not found,
    1 = resolved, 2+ = ambiguous). Matches against basename, YAML `title`,
    and `aliases`, all NFC-casefold-normalized - same normalization rule
    as obsidian-search/pathutil (REQ-FND-0001), never a fuzzy/substring
    guess for this destructive-adjacent operation (an index rebuild for
    the wrong file wastes an LLM/embedding budget silently)."""
    wanted = {_norm(n): n for n in names}
    found: Dict[str, List[str]] = {n: [] for n in names}
    for rel in linkgraph.iter_vault_files(Path(profile.vault_path), profile.scope, extensions={".md"}):
        stem = Path(rel).stem
        candidates = {_norm(stem)}
        try:
            raw = md.read_text(Path(profile.vault_path) / rel)
            meta = md.parse_frontmatter(raw).meta
            title = meta.get("title")
            if title:
                candidates.add(_norm(str(title)))
            aliases = meta.get("aliases") or []
            if isinstance(aliases, str):
                aliases = [aliases]
            candidates.update(_norm(str(a)) for a in aliases)
        except OSError:
            pass
        for key in candidates & wanted.keys():
            found[wanted[key]].append(rel)
    return found


def cmd_resync_titles(args, profile: VaultProfile) -> int:
    resolved = _resolve_titles(profile, args.titles)
    results = []
    unresolved = [name for name, paths in resolved.items() if len(paths) != 1]
    for name, paths in resolved.items():
        if not paths:
            results.append(indexing.IndexFileResult(name, "not_indexable", error="no matching file found by name/title/alias"))
        elif len(paths) > 1:
            results.append(indexing.IndexFileResult(
                name, "not_indexable",
                error=f"ambiguous - {len(paths)} files match this name: {paths}. Use resync --paths with the exact path instead.",
            ))
        else:
            rel_path = paths[0]
            raw = md.read_text(Path(profile.vault_path) / rel_path)
            results.append(indexing.index_file(profile, rel_path, raw))
    rc = _print_results(results, args.format)
    return 2 if unresolved and args.format != "json" and rc == 0 else rc


def cmd_delete(args, profile: VaultProfile) -> int:
    results = [indexing.delete_file(profile, p) for p in args.paths]
    return _print_results(results, args.format)


def cmd_rename(args, profile: VaultProfile) -> int:
    results = [indexing.delete_file(profile, args.old)]
    full = Path(profile.vault_path) / args.new
    if not full.is_file():
        results.append(indexing.IndexFileResult(args.new, "not_indexable", error="new path not found in vault"))
    else:
        raw = md.read_text(full)
        results.append(indexing.index_file(profile, args.new, raw))
    return _print_results(results, args.format)


def cmd_full(args, profile: VaultProfile) -> int:
    results = []
    skipped_non_md = 0
    for rel in linkgraph.iter_vault_files(Path(profile.vault_path), profile.scope):
        if Path(rel).suffix.lower() not in INDEXABLE_EXTENSIONS:
            skipped_non_md += 1
            continue
        raw = md.read_text(Path(profile.vault_path) / rel)
        results.append(indexing.index_file(profile, rel, raw))
    rc = _print_results(results, args.format)
    if args.format != "json" and skipped_non_md:
        print(f"\n({skipped_non_md} non-.md file(s) skipped - .canvas/.base indexing not yet implemented)")
    return rc


def cmd_status(args, profile: VaultProfile) -> int:
    client = vs.get_client(profile)
    rows = [{"source_path": p, "vectors": vs.count_by_source_path(client, profile, p)} for p in args.paths]
    if args.format == "json":
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for row in rows:
            flag = "" if row["vectors"] else "  ⚠️ not indexed"
            print(f"{row['vectors']:4d} vectors  {row['source_path']}{flag}")
    return 0


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="profile file path or registered vault id")
    common.add_argument("--format", default="md", choices=["md", "json"])

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_resync = sub.add_parser("resync", help="full rebuild for explicit vault-relative paths", parents=[common])
    p_resync.add_argument("--paths", nargs="+", required=True)

    p_titles = sub.add_parser("resync-titles", help="full rebuild for article names/titles instead of paths", parents=[common])
    p_titles.add_argument("--titles", nargs="+", required=True)

    p_delete = sub.add_parser("delete", help="a file was removed - delete its vectors", parents=[common])
    p_delete.add_argument("--paths", nargs="+", required=True)

    p_rename = sub.add_parser("rename", help="delete old path's vectors, index the new path fresh", parents=[common])
    p_rename.add_argument("--old", required=True)
    p_rename.add_argument("--new", required=True)

    sub.add_parser("full", help="resync every indexable file in the vault", parents=[common])

    p_status = sub.add_parser("status", help="how many vectors exist for given paths, no changes made", parents=[common])
    p_status.add_argument("--paths", nargs="+", required=True)

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "resync":
        return cmd_resync(args, profile)
    if args.command == "resync-titles":
        return cmd_resync_titles(args, profile)
    if args.command == "delete":
        return cmd_delete(args, profile)
    if args.command == "rename":
        return cmd_rename(args, profile)
    if args.command == "full":
        return cmd_full(args, profile)
    if args.command == "status":
        return cmd_status(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
