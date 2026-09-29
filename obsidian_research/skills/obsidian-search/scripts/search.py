#!/usr/bin/env python3
"""obsidian-search: find notes by name/title/alias/text, or list a folder.

Implements spec passport 01-obsidian-search.md (US-001) and the folder
listing mode REQ-RET-0003. See SKILL.md in this skill's directory for how
Claude should call this and read its output; this file is the algorithmic
half only (network call, ranking-by-evidence, filters, pagination) - it
does not decide *what* to search for, that is Claude's job.

Examples
--------
  search.py --query "GraphRAG обновление графа" --mode deep
  search.py --folder "PARA/projects" --recursive false
  search.py --query "python" --filters tag=MOC --format json
  # Unsure which language/form a term is under in the vault (title, alias,
  # or body only)? Pass --query more than once rather than gluing terms
  # into one string - each is probed independently against Omnisearch AND
  # against filename/title/alias/H1, and the report keeps the *strongest*
  # match found for a note across all of them:
  search.py --query "чанкинг" --query "chunking"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import linkgraph, markdown as md, pathutil  # noqa: E402
from obsidian_common.omnisearch import OmnisearchClient, OmnisearchUnavailable, clean_excerpt  # noqa: E402
from obsidian_common.profile import ProfileError, VaultProfile, resolve_profile  # noqa: E402

MODE_DEFAULT_LIMIT = {"narrow": 5, "deep": 20}


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s).strip().casefold()


def build_query_list(base_queries: List[str], term_variants: Dict[str, list]) -> List[tuple]:
    """One (reason, query) pair per distinct query actually worth trying:
    every `--query` the caller gave as `("original", ...)`, plus S3's
    controlled RU/EN/abbreviation expansion for each (config-driven, never
    invented at run time - see profile.term_variants in
    config/vault_profile.example.yaml). Order preserved; a query that
    normalizes the same as one already in the list is dropped, whichever
    base query or variant expansion it came from.

    Multiple `--query` values are the fix for a real failure mode: a
    caller who glues "чанкинг chunking" into one string gets only whatever
    Omnisearch's full-text ranking finds for that exact glued phrase, even
    if the target note's alias is the *separate* word "chunking" - neither
    an exact nor a substring match against the combined string. Passing
    each term as its own `--query` probes Omnisearch and the filename/
    title/alias/H1 tiers independently per term (see classify_match)
    without the caller needing to pre-declare a term_variants mapping.
    """
    queries: List[tuple] = []
    seen = set()
    for base in base_queries:
        base = base.strip()
        if not base:
            continue
        nb = _norm(base)
        if nb not in seen:
            queries.append(("original", base))
            seen.add(nb)
        for canonical, variants in term_variants.items():
            pool = [canonical] + list(variants)
            if any(_norm(v) == nb for v in pool):
                for v in pool:
                    if _norm(v) not in seen:
                        queries.append((f"variant_of:{canonical}", v))
                        seen.add(_norm(v))
    return queries


def read_note_signals(vault_path: Path, rel_path: str) -> dict:
    """Cheap per-hit signals needed for match-type classification only -
    frontmatter + first H1, never the full body (that stays reader's job)."""
    full = Path(vault_path) / rel_path
    try:
        raw = md.read_text(full)
    except OSError:
        return {"title": None, "aliases": [], "h1": None}
    parsed = md.parse_frontmatter(raw)
    title = parsed.meta.get("title")
    aliases = parsed.meta.get("aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    headings = md.parse_headings(parsed.body, parsed.body_start_line)
    h1 = next((h.title for h in headings if h.level == 1), None)
    return {"title": title, "aliases": aliases, "h1": h1, "tags": parsed.meta.get("tags") or []}


_MATCH_TIER_ORDER = [
    "exact_filename", "filename_without_prefix", "yaml_title", "alias_exact",
    "heading_h1", "filename_contains", "title_contains", "alias_contains",
    "heading_contains", "text",
]
_MATCH_TIER_RANK = {t: i for i, t in enumerate(_MATCH_TIER_ORDER)}


def classify_match_one(query: str, basename_no_ext: str, naming, signals: dict) -> str:
    """S1 priority order for a single query string: exact filename >
    filename w/o MOC_/HUB_ > YAML title > aliases > H1 > text. Each tier
    also accepts substring containment, ranked weaker than an exact hit at
    the same tier. See classify_match for combining several queries."""
    nq = _norm(query)
    nb = _norm(basename_no_ext)
    if nq == nb:
        return "exact_filename"
    stripped = basename_no_ext
    for prefix in (naming.moc_prefix, naming.hub_prefix):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
    if _norm(stripped) == nq:
        return "filename_without_prefix"
    title = signals.get("title")
    if title and _norm(str(title)) == nq:
        return "yaml_title"
    if any(_norm(str(a)) == nq for a in signals.get("aliases", [])):
        return "alias_exact"
    h1 = signals.get("h1")
    if h1 and _norm(h1) == nq:
        return "heading_h1"
    if nq in nb:
        return "filename_contains"
    if title and nq in _norm(str(title)):
        return "title_contains"
    if any(nq in _norm(str(a)) for a in signals.get("aliases", [])):
        return "alias_contains"
    if h1 and nq in _norm(h1):
        return "heading_contains"
    return "text"


def classify_match(queries: List[str], basename_no_ext: str, naming, signals: dict):
    """Runs classify_match_one for every query actually searched (the
    original --query value(s) plus any term_variants expansion) and keeps
    the *strongest* tier found, with which query produced it.

    This is what makes multiple --query values (or a configured variant)
    actually pay off: a hit found only because "chunking" is an exact
    alias must be reported as alias_exact even when a *different* query
    in the same run - e.g. the combined "чанкинг chunking" - would only
    have classified as a weak 'text' match on its own. Classifying against
    just the first/original query (the previous behaviour) silently threw
    this away whenever a variant or a second --query was what really found
    the note by name rather than by body text.
    """
    best_type, best_query = "text", (queries[0] if queries else "")
    best_rank = _MATCH_TIER_RANK["text"]
    for q in queries:
        t = classify_match_one(q, basename_no_ext, naming, signals)
        rank = _MATCH_TIER_RANK[t]
        if rank < best_rank:
            best_rank, best_type, best_query = rank, t, q
    return best_type, best_query


def omnisearch_stage(profile: VaultProfile, queries: List[tuple], limit: int) -> tuple:
    """Returns (merged_hits_by_path, provenance, unavailable: bool, error)."""
    if not profile.omnisearch.enabled:
        return {}, [], True, "omnisearch disabled in profile"
    client = OmnisearchClient(
        profile.omnisearch.host, profile.omnisearch.port, profile.omnisearch.timeout
    )
    merged: Dict[str, dict] = {}
    provenance = []
    for reason, q in queries:
        try:
            hits = client.search(q)
        except OmnisearchUnavailable as exc:
            return merged, provenance, True, str(exc)
        for h in hits:
            if h.vault and profile.vault_id and h.vault != profile.vault_id:
                # Omnisearch's HTTP server answers for *all* vaults open in
                # this Obsidian instance; only keep the connected one.
                continue
            rel = h.path
            entry = merged.setdefault(
                rel,
                {"path": rel, "basename": h.basename, "score": h.score,
                 "excerpt": clean_excerpt(h.excerpt), "found_via": []},
            )
            entry["score"] = max(entry["score"], h.score)
            entry["found_via"].append({"query": q, "reason": reason, "score": h.score})
        provenance.append({"query": q, "reason": reason, "hit_count": len(hits)})
    return merged, provenance, False, None


def fallback_search(vault_path, scope, queries: List[tuple]) -> Dict[str, dict]:
    """S6: filename/title/aliases/H1 substring fallback when Omnisearch is
    down. Deliberately does not also grep full body text here - that is a
    much larger, slower promise ('text' tier) this fallback path does not
    make; it is flagged in the report as reduced coverage, not silently
    equated with a normal Omnisearch run."""
    merged: Dict[str, dict] = {}
    norm_queries = [(_norm(q), reason, q) for reason, q in queries]
    for rel in linkgraph.iter_vault_files(vault_path, scope, extensions={".md"}):
        basename = PurePosixPath(rel).stem
        signals = read_note_signals(vault_path, rel)
        haystacks = [basename, str(signals.get("title") or "")]
        haystacks += [str(a) for a in signals.get("aliases", [])]
        if signals.get("h1"):
            haystacks.append(signals["h1"])
        nb_all = [_norm(h) for h in haystacks if h]
        for nq, reason, q in norm_queries:
            if any(nq in h for h in nb_all):
                entry = merged.setdefault(
                    rel, {"path": rel, "basename": basename, "score": 0.0,
                          "excerpt": "", "found_via": []}
                )
                entry["found_via"].append({"query": q, "reason": reason, "score": None})
    return merged


def folder_listing(vault_path: Path, scope, folder: str, recursive: bool) -> dict:
    folder_norm = folder.strip("/")
    full_folder = vault_path / folder_norm if folder_norm else vault_path
    if folder_norm and not full_folder.is_dir():
        return {"error": "folder_not_found", "folder": folder_norm}
    entries = []
    for rel in linkgraph.iter_vault_files(vault_path, scope):
        rel_p = PurePosixPath(rel)
        if folder_norm:
            folder_parts = PurePosixPath(folder_norm).parts
            if rel_p.parts[: len(folder_parts)] != folder_parts:
                continue
            remainder = rel_p.parts[len(folder_parts):]
        else:
            remainder = rel_p.parts
        if not remainder:
            continue
        if not recursive and len(remainder) != 1:
            continue
        entries.append({"path": rel, "name": rel_p.name, "type": rel_p.suffix.lstrip(".")})
    entries.sort(key=lambda e: e["path"])
    return {"folder": folder_norm or ".", "recursive": recursive, "count": len(entries), "files": entries}


def apply_filters(hits: List[dict], vault_path: Path, filters: Dict[str, str]) -> List[dict]:
    if not filters:
        return hits
    out = []
    for h in hits:
        full = Path(vault_path) / h["path"]
        try:
            raw = md.read_text(full)
        except OSError:
            continue
        meta = md.parse_frontmatter(raw).meta
        ok = True
        for key, want in filters.items():
            if key == "tag":
                tags = meta.get("tags") or []
                if isinstance(tags, str):
                    tags = [tags]
                if want not in [str(t) for t in tags]:
                    ok = False
                    break
            elif key == "folder":
                if not h["path"].startswith(want.strip("/")):
                    ok = False
                    break
            else:
                if str(meta.get(key)) != want:
                    ok = False
                    break
        if ok:
            out.append(h)
    return out


def parse_filters(raw: Optional[str]) -> Dict[str, str]:
    if not raw:
        return {}
    out = {}
    for part in raw.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--query", action="append",
                     help="search text (omit for folder listing); repeat for several "
                          "independent terms, e.g. --query \"чанкинг\" --query \"chunking\"")
    ap.add_argument("--folder", help="vault-relative folder for folder-listing mode / folder filter")
    ap.add_argument("--recursive", default="true", choices=["true", "false"])
    ap.add_argument("--mode", default="narrow", choices=["narrow", "deep"])
    ap.add_argument("--filters", help="comma list of key=value (tag=, folder=, status=, type=, ...)")
    ap.add_argument("--limit", type=int, help="override the mode's default result count")
    ap.add_argument("--profile", help="profile file path or registered vault id")
    ap.add_argument("--format", default="md", choices=["md", "json"])
    args = ap.parse_args()

    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    recursive = args.recursive == "true"

    if args.folder and not args.query:
        result = folder_listing(profile.vault_path, profile.scope, args.folder, recursive)
        if args.format == "json":
            print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        else:
            if "error" in result:
                print(f"**Ошибка:** папка `{result['folder']}` не найдена или недоступна.")
            else:
                print(f"### Файлы в `{result['folder']}` (recursive={recursive}): {result['count']}\n")
                for e in result["files"]:
                    print(f"- `{e['path']}` ({e['type'] or 'no-ext'})")
        return 0

    if not args.query:
        print("error: provide --query, or --folder for folder-listing mode", file=sys.stderr)
        return 2

    limit = args.limit or MODE_DEFAULT_LIMIT[args.mode]
    filters = parse_filters(args.filters)
    queries = build_query_list(args.query, profile.term_variants)
    all_query_strings = [q for _, q in queries]

    merged, provenance, unavailable, err = omnisearch_stage(profile, queries, limit)
    used_fallback = False
    if unavailable:
        used_fallback = True
        merged = fallback_search(profile.vault_path, profile.scope, queries)

    hits = sorted(merged.values(), key=lambda h: h["score"], reverse=True)
    hits = apply_filters(hits, profile.vault_path, filters)

    report_rows = []
    for h in hits[:limit]:
        basename_no_ext = PurePosixPath(h["path"]).stem
        signals = read_note_signals(profile.vault_path, h["path"])
        match_type, matched_query = classify_match(all_query_strings, basename_no_ext, profile.naming, signals)
        cls = pathutil.classify_navigation_name(basename_no_ext, profile.naming)
        report_rows.append(
            {
                "path": h["path"],
                "basename": h["basename"],
                "match_type": match_type,
                "matched_via_query": matched_query,
                "score": h["score"],
                "excerpt": h.get("excerpt", ""),
                "found_via": h["found_via"],
                "naming_convention": {
                    "kind": cls.kind,
                    "compliant": cls.compliant,
                    "legacy_pattern": cls.legacy_pattern,
                } if cls.kind else None,
            }
        )

    result = {
        "queries": args.query,
        "mode": args.mode,
        "queries_used": [{"query": q, "reason": r} for r, q in queries],
        "omnisearch_unavailable": unavailable,
        "omnisearch_error": err,
        "used_fallback": used_fallback,
        "filters": filters,
        "limit": limit,
        "total_candidates_before_limit": len(hits),
        "results": report_rows,
    }

    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
        return 0

    query_label = " + ".join(f"«{q}»" for q in args.query)
    print(f"### Поиск: {query_label} (mode={args.mode})\n")
    if unavailable:
        print(f"⚠️ **omnisearch_unavailable** — {err}\n\nИспользован резервный поиск по имени/title/aliases/H1 "
              "(без полнотекстового поиска по телу заметок).\n")
    if len(queries) > 1:
        print("Запросы:", ", ".join(f"`{q}`({r})" for r, q in queries), "\n")
    if not report_rows:
        print("Ничего не найдено в разрешённом scope.")
        return 0
    print("| Заметка | Путь | Совпадение | По запросу | Пояснение |")
    print("|---|---|---|---|---|")
    for r in report_rows:
        note_flag = ""
        if r["naming_convention"] and not r["naming_convention"]["compliant"]:
            note_flag = f" ⚠️legacy-{r['naming_convention']['kind']}"
        matched_via = f"`{r['matched_via_query']}`" if len(args.query) > 1 else ""
        print(f"| {r['basename']}{note_flag} | `{r['path']}` | {r['match_type']} | {matched_via} | "
              f"{r['excerpt'][:80].replace(chr(10), ' ') or '—'} |")
    if len(hits) > limit:
        print(f"\n_Показано {limit} из {len(hits)} кандидатов (лимит режима {args.mode})._")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
