#!/usr/bin/env python3
"""obsidian-gap-search: evaluate a HUB/MOC/topic's local coverage and plan
external search queries for what's missing - never runs a web search,
never writes to the vault.

Implements spec passport 19-obsidian-gap-search.md (US-015), ADR-0007 and
REQ-RET-0004/0005. The judgment calls (is this gap actually significant,
what's a good research question, is a query text well-formed) stay
Claude's - this script handles what's mechanical: pulling the structured
checklist out of a HUB/MOC so nothing gets skipped by accident, batching
coverage lookups, and - the part that matters most - verifying every
personal/author-targeted query in a finished plan actually traces back to
a name found verbatim in a real, cited fragment (REQ-RET-0005: "имя не
угадывать"). A plan that fails validate-plan should not go out with
status other than 'planned', and should not go out at all with an
unverified author.

Subcommands
-----------
  read-target     - extract the checklist from a HUB or MOC (purpose/
                    perspective question, terms, stages) to compare
                    coverage against.
  check-coverage  - batch Omnisearch lookup for a list of terms/questions,
                    so many candidates can be checked in one call instead
                    of one obsidian-search invocation per term.
  validate-plan   - mechanically checks an ExternalSearchQueryPlan JSON:
                    required fields, status=planned only, near-duplicate
                    queries flagged, and author-query provenance verified
                    against the actual cited file content.
  render          - format CoverageGap[] + the validated plan as the final
                    report. Print-only - this skill never writes a note.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import markdown as md  # noqa: E402
from obsidian_common.omnisearch import OmnisearchClient, OmnisearchUnavailable, clean_excerpt  # noqa: E402
from obsidian_common.profile import ProfileError, resolve_profile  # noqa: E402

REQUIRED_PLAN_FIELDS = [
    "research_question", "query_text", "language", "purpose",
    "expected_source_type", "stop_criterion",
]


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", re.sub(r"\s+", " ", s.strip())).casefold()


def _read_hub_target(vault_path: Path, rel_path: str) -> dict:
    full = Path(vault_path) / rel_path
    if not full.is_file():
        return {"error": "not_found", "path": rel_path}
    raw = md.read_text(full)
    parsed = md.parse_frontmatter(raw)
    headings = md.parse_headings(parsed.body, parsed.body_start_line)
    stages_heading = next((h for h in headings if h.title == "Этапы"), None)
    stages = []
    if stages_heading:
        for h in headings:
            # h is a *direct* child of the 'Этапы' heading regardless of
            # what sits above it (a HUB's .md may or may not open with an
            # H1 title) - its full ancestor path minus itself must equal
            # 'Этапы'-heading's own path exactly.
            if h.level == stages_heading.level + 1 and h.path[:-1] == stages_heading.path:
                stages.append({"name": h.title, "text": md.own_text(raw, headings, h).strip()})
    return {
        "type": "hub", "path": rel_path,
        "purpose": parsed.meta.get("purpose"), "summary": parsed.meta.get("summary"),
        "terms": parsed.meta.get("terms") or [], "route_type": parsed.meta.get("route_type"),
        "stages": stages,
    }


def _read_moc_target(vault_path: Path, rel_path: str) -> dict:
    full = Path(vault_path) / rel_path
    if not full.is_file():
        return {"error": "not_found", "path": rel_path}
    meta = md.parse_frontmatter(md.read_text(full)).meta
    return {
        "type": "moc", "path": rel_path,
        "perspective": meta.get("perspective"), "perspective_question": meta.get("perspective_question"),
        "summary": meta.get("summary"), "terms": meta.get("terms") or [],
    }


def cmd_read_target(args, profile) -> int:
    if args.hub:
        result = _read_hub_target(profile.vault_path, args.hub)
    else:
        result = _read_moc_target(profile.vault_path, args.moc)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 1 if "error" in result else 0


def cmd_check_coverage(args, profile) -> int:
    terms = json.loads(Path(args.terms_file).read_text(encoding="utf-8"))
    if not profile.omnisearch.enabled:
        print(json.dumps({"error": "omnisearch_disabled"}, ensure_ascii=False, indent=2, default=str))
        return 1
    client = OmnisearchClient(profile.omnisearch.host, profile.omnisearch.port, profile.omnisearch.timeout)
    results = {}
    unavailable = False
    for term in terms:
        try:
            hits = client.search(term)
        except OmnisearchUnavailable as exc:
            results[term] = {"error": "omnisearch_unavailable", "detail": str(exc)}
            unavailable = True
            continue
        hits = [h for h in hits if not h.vault or not profile.vault_id or h.vault == profile.vault_id]
        results[term] = [
            {"path": h.path, "basename": h.basename, "score": h.score, "excerpt": clean_excerpt(h.excerpt)}
            for h in hits[:5]
        ]
    payload = {
        "terms_checked": terms, "results": results, "omnisearch_unavailable": unavailable,
        "note": ("Absence of a hit does not by itself prove a gap (REQ-RET-0004) - "
                 "a term can be covered under different wording, or inside a section "
                 "that ranks low on lexical search. Read what *is* found before concluding."),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


def _validate_plan_entries(vault_path: Path, entries: List[dict]) -> List[dict]:
    issues = []
    seen: dict = {}
    for i, entry in enumerate(entries):
        ref = entry.get("research_question", f"entry[{i}]")
        status = entry.get("status")
        if status != "planned":
            issues.append({"index": i, "ref": ref, "severity": "error",
                            "message": f"status must be 'planned' (never 'searched'/'verified' - this "
                                       f"skill does not execute anything), got {status!r}"})
        for field_name in REQUIRED_PLAN_FIELDS:
            if not entry.get(field_name):
                issues.append({"index": i, "ref": ref, "severity": "error",
                                "message": f"missing required field {field_name!r}"})
        nq = _norm(entry.get("query_text", ""))
        if nq:
            if nq in seen:
                issues.append({"index": i, "ref": ref, "severity": "warning",
                                "message": f"query_text near-duplicates entry {seen[nq]} - "
                                           "algorithms.md §6 wants non-repeating queries"})
            else:
                seen[nq] = i

        author = entry.get("author")
        if author:
            src = entry.get("author_source_path")
            quote = entry.get("author_source_quote")
            if not src or not quote:
                issues.append({"index": i, "ref": ref, "severity": "error",
                                "message": "an 'author' query requires both 'author_source_path' and "
                                           "'author_source_quote' - REQ-RET-0005 forbids guessing a name"})
                continue
            full = Path(vault_path) / src
            if not full.is_file():
                issues.append({"index": i, "ref": ref, "severity": "error",
                                "message": f"author_source_path does not exist: {src}"})
                continue
            text = md.read_text(full)
            if quote.strip() not in text:
                issues.append({"index": i, "ref": ref, "severity": "error",
                                "message": "author_source_quote was not found verbatim in author_source_path - "
                                           "cannot verify this claim was actually read there"})
            if author.strip() not in text:
                issues.append({"index": i, "ref": ref, "severity": "error",
                                "message": f"author name {author!r} was not found verbatim in author_source_path - "
                                           "REQ-RET-0005: no confirmed name, no personal query"})
    return issues


def cmd_validate_plan(args, profile) -> int:
    entries = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
    issues = _validate_plan_entries(profile.vault_path, entries)
    result = {
        "total_entries": len(entries),
        "issues": issues,
        "ok": not any(i["severity"] == "error" for i in issues),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


def cmd_render(args, profile) -> int:
    gaps = json.loads(Path(args.gaps_file).read_text(encoding="utf-8"))
    plan = json.loads(Path(args.plan_file).read_text(encoding="utf-8"))
    issues = _validate_plan_entries(profile.vault_path, plan)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        print("error: plan fails validation, fix before rendering:", file=sys.stderr)
        for i in errors:
            print(f"  - [{i['ref']}] {i['message']}", file=sys.stderr)
        return 2

    lines = ["## Пробелы покрытия\n"]
    if not gaps:
        lines.append("_Существенных пробелов не найдено в пределах проверенной области._\n")
    for g in gaps:
        lines.append(f"### {g.get('topic_or_question','?')}")
        lines.append(f"- Тип: `{g.get('gap_type','?')}`, уверенность: `{g.get('confidence','?')}`")
        if g.get("nearest_coverage"):
            nc = g["nearest_coverage"]
            lines.append(f"- Ближайшее покрытие: `{nc.get('path')}`" + (f" #{nc['heading']}" if nc.get("heading") else ""))
        if g.get("missing"):
            lines.append(f"- Не хватает: {g['missing']}")
        if g.get("limitations"):
            lines.append(f"- Ограничения: {g['limitations']}")
        lines.append("")

    lines.append("## План внешних запросов (status: planned - ничего не искалось)\n")
    if not plan:
        lines.append("_Внутреннего покрытия достаточно, внешние запросы не требуются._\n")
    for i, e in enumerate(sorted(plan, key=lambda x: x.get("priority", 999)), start=1):
        lines.append(f"{i}. **{e.get('research_question','?')}** ({e.get('language','?')})")
        lines.append(f"   `{e.get('query_text','')}`")
        lines.append(f"   Цель: {e.get('purpose','')}. Ожидаемый источник: {e.get('expected_source_type','')}. "
                      f"Критерий остановки: {e.get('stop_criterion','')}.")
        if e.get("author"):
            lines.append(f"   Автор: {e['author']} (подтверждено в `{e.get('author_source_path')}`)")
        lines.append("")

    print("\n".join(lines))
    return 0


def main() -> int:
    # --profile is defined on each subparser (via parents=), not the top
    # level - see workflow.py's main() for why ("script.py subcommand
    # --profile X" must work, not only "script.py --profile X subcommand").
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="profile file path or registered vault id")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_target = sub.add_parser("read-target", help="extract the checklist from a HUB or MOC", parents=[common])
    g = p_target.add_mutually_exclusive_group(required=True)
    g.add_argument("--hub")
    g.add_argument("--moc")

    p_cov = sub.add_parser("check-coverage", help="batch Omnisearch lookup for candidate terms/questions", parents=[common])
    p_cov.add_argument("--terms-file", required=True, help="JSON array of strings")

    p_val = sub.add_parser("validate-plan", help="mechanical checks on an ExternalSearchQueryPlan JSON", parents=[common])
    p_val.add_argument("--plan-file", required=True)

    p_render = sub.add_parser("render", help="format the final gaps + plan report (never writes to the vault)", parents=[common])
    p_render.add_argument("--gaps-file", required=True)
    p_render.add_argument("--plan-file", required=True)

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "read-target":
        return cmd_read_target(args, profile)
    if args.command == "check-coverage":
        return cmd_check_coverage(args, profile)
    if args.command == "validate-plan":
        return cmd_validate_plan(args, profile)
    if args.command == "render":
        return cmd_render(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
