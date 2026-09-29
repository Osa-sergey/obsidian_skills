#!/usr/bin/env python3
"""obsidian-workflow: routing helpers for the full research-and-develop
cycle across skills 1-19.

Implements spec passport 10-obsidian-workflow.md (US-012/US-014/US-015).
Which *stages* a given request needs (algorithm §... "выбирает только
необходимые этапы") is Claude's own judgment from the request, guided by
this skill's SKILL.md - not something this script decides. What the
script *does* do: report which of the 19 skills actually exist to route
to right now (the roster keeps changing as more get built), and turn a
pile of ChangeRecord-shaped JSON from a multi-skill run into the one
consolidated "Итог запуска" the passport requires (result-formats.md) -
including the mandatory index_dirty flag, since obsidian-index-sync
(skill 18) is not built in this project yet.

Subcommands
-----------
  list-skills   - which of the 19 skills are actually installed, so a
                  workflow route can be checked against reality before
                  Claude promises a step it can't currently take.
  summarize-run - aggregate ChangeRecord JSON from however many
                  author/revise/moc/hub/link/metadata apply calls a run
                  made into one honest final report.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_SKILLS_DIR = Path(__file__).resolve().parents[2]

# The full roster from docs/spec/skills/index.md, in spec order. Kept
# here (not derived from the filesystem alone) so a *missing* skill still
# shows up as "not built" rather than silently disappearing from the list.
ALL_SKILLS = [
    (1, "obsidian-search", "find notes by name/title/alias/text or list a folder"),
    (2, "obsidian-context", "graph context around notes, by depth"),
    (3, "obsidian-research", "synthesis over read materials, with evidence"),
    (4, "obsidian-author", "new structured articles"),
    (5, "obsidian-revise", "addressed edits to existing articles"),
    (6, "obsidian-link", "cross-links between articles"),
    (7, "obsidian-metadata", "YAML frontmatter validation/normalization"),
    (8, "obsidian-moc", "hierarchical Maps of Content"),
    (9, "obsidian-hub", "paired Markdown+Canvas work/learning routes"),
    (10, "obsidian-workflow", "this skill - routes the others"),
    (11, "obsidian-query", "execute saved Dataview/Bases queries"),
    (12, "obsidian-query-builder", "build/catalog Dataview/Bases queries"),
    (13, "obsidian-semantic-search", "RAPTOR semantic search"),
    (14, "obsidian-retrieve", "hybrid retrieval orchestration"),
    (15, "obsidian-fragment-reader", "addressed reading of one paragraph/section"),
    (16, "obsidian-evidence", "evidence-set extraction"),
    (17, "obsidian-qa", "token-economical narrow QA"),
    (18, "obsidian-index-sync", "mandatory RAPTOR resync after applied writes"),
    (19, "obsidian-gap-search", "coverage gaps + external search query plans"),
]

# result-formats.md "Итог запуска": a run's records get grouped into these
# buckets, in this order, for the final report.
STATUS_ORDER = ["applied", "unchanged", "conflict", "error"]


def cmd_list_skills(args) -> int:
    installed = {
        p.name for p in REPO_SKILLS_DIR.iterdir()
        if p.is_dir() and (p / "SKILL.md").is_file()
    } if REPO_SKILLS_DIR.is_dir() else set()

    rows = []
    for num, name, desc in ALL_SKILLS:
        rows.append({"num": num, "name": name, "description": desc, "built": name in installed})

    if args.format == "json":
        print(json.dumps({"skills": rows, "built_count": sum(r["built"] for r in rows)},
                          ensure_ascii=False, indent=2, default=str))
        return 0

    print(f"{sum(r['built'] for r in rows)}/{len(rows)} skills built:\n")
    for r in rows:
        mark = "✅" if r["built"] else "⬜"
        print(f"{mark} {r['num']:>2}. {r['name']} — {r['description']}")
    return 0


def cmd_summarize_run(args) -> int:
    try:
        records = json.loads(Path(args.records_file).read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"error: not_found: {args.records_file}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"error: {args.records_file} is not valid JSON: {exc}", file=sys.stderr)
        return 2
    if not isinstance(records, list):
        print(f"error: {args.records_file} must contain a JSON array of records", file=sys.stderr)
        return 2
    by_status = {s: [] for s in STATUS_ORDER}
    unknown_status = []
    for rec in records:
        status = rec.get("status")
        if status in by_status:
            by_status[status].append(rec)
        else:
            unknown_status.append(rec)

    any_applied = bool(by_status["applied"])
    all_ok = not by_status["conflict"] and not by_status["error"] and not unknown_status
    summary = {
        "total_records": len(records),
        "counts": {s: len(by_status[s]) for s in STATUS_ORDER},
        "applied": by_status["applied"],
        "unchanged": by_status["unchanged"],
        "conflict": by_status["conflict"],
        "error": by_status["error"],
        "unknown_status_records": unknown_status,
        "all_ok": all_ok,
        "index_dirty": any_applied,
        "index_dirty_note": (
            "obsidian-index-sync (skill 18) is not built in this project - "
            "if any record above is 'applied', the vault's semantic index (if "
            "any exists at all) does not reflect it. Say this in the final "
            "report; never imply search/index freshness after a write."
            if any_applied else
            "no applied writes in this run - nothing to resync."
        ),
    }

    if args.format == "json":
        print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
        return 0 if all_ok else 1

    print(f"### Итог запуска: {len(records)} операций\n")
    for s in STATUS_ORDER:
        items = by_status[s]
        if not items:
            continue
        print(f"**{s}** ({len(items)}):")
        for r in items:
            print(f"- `{r.get('path','?')}` — {r.get('operation','?')}: {r.get('detail','')}")
        print()
    if unknown_status:
        print(f"⚠️ {len(unknown_status)} record(s) with an unrecognized status field - treat as unresolved.\n")
    if not all_ok:
        print("⚠️ **Пакет не полностью применён** — не отмечай весь запуск завершённым "
              "(acceptance.md: «Отчёт не объявляет весь пакет готовым»).\n")
    print(f"index_dirty: {summary['index_dirty']} — {summary['index_dirty_note']}")
    return 0 if all_ok else 1


def main() -> int:
    # --format must be defined on each subparser too (via parents=), not
    # only on the top-level parser: argparse hands every token *after* the
    # subcommand name to the subparser, which otherwise has no idea what
    # --format is - "script.py subcommand --format json" (the natural way
    # to type it, and how every SKILL.md example writes it) would fail
    # with "unrecognized arguments" otherwise. Keeping it on the top-level
    # parser too, instead of only on the subparsers, re-breaks the
    # opposite order ("script.py --format json subcommand"): argparse
    # parses the subparser's own default over top-level's value.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--format", default="md", choices=["md", "json"])

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("list-skills", help="which of the 19 skills are actually installed", parents=[common])

    p_sum = sub.add_parser("summarize-run", help="aggregate ChangeRecord JSON from a multi-skill run", parents=[common])
    p_sum.add_argument("--records-file", required=True,
                        help="JSON array of ChangeRecord-shaped objects (path/operation/status/detail), "
                             "e.g. collected from author/revise/moc/hub/link/metadata 'apply' output")

    args = ap.parse_args()

    if args.command == "list-skills":
        return cmd_list_skills(args)
    if args.command == "summarize-run":
        return cmd_summarize_run(args)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
