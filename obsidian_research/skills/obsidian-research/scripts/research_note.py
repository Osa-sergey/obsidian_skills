#!/usr/bin/env python3
"""obsidian-research: addressed fragment reading, citation validation, and
research-note rendering.

Implements the mechanical parts of spec passport 03-obsidian-research.md
(US-003) that do not require judgment. The actual synthesis - comparing
approaches, deciding what is a genuine contradiction, what is missing, what
to recommend - is Claude's job and stays out of this script on purpose (see
SKILL.md). What belongs here is what a script can get right every time:

  fragment   - read one addressed section of a vault note (heading-exact,
               not semantic - skill 13/RAPTOR does not exist yet).
  validate   - check a claim -> evidence map against the live vault before
               it ships: does the cited path/heading actually exist? This
               is the mechanical half of foundation.md §2.3 rule 5 ("не
               представлять ссылку на непрочитанный источник как
               подтверждение") - it cannot verify Claude actually read the
               text, but it can catch a hallucinated path or heading.
  dedup-sources - group evidence items that cite the same primary source
               (acceptance.md §7: "Две заметки повторяют одну публикацию —
               это один первоисточник, а не два независимых подтверждения").
  render     - turn a findings JSON object into the fixed research-note
               structure from defaults.md §11 block R2 (synthesis ->
               findings -> comparisons/contradictions -> gaps ->
               implications -> vault changes), so every research note has
               the same shape regardless of who/what filled it in.

Examples
--------
  research_note.py fragment --path "zettelkasten/notes/GraphRAG (Microsoft).md" --heading "Краткое описание"
  research_note.py validate --evidence evidence.json
  research_note.py dedup-sources --sources sources.json
  research_note.py render --findings findings.json --out "PARA/resources/Research - GraphRAG updates.md"
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import markdown as md  # noqa: E402
from obsidian_common.profile import ProfileError, resolve_profile  # noqa: E402


def cmd_fragment(args, profile) -> int:
    result = md.read_fragment(profile.vault_path, args.path, args.heading)
    payload = {
        "status": result.status,
        "path": result.path,
        "heading_path": result.heading_path,
        "line_start": result.line_start,
        "line_end": result.line_end,
        "content_hash": result.content_hash,
        "candidates": result.candidates,
        "text": result.text,
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"status={result.status} path={result.path} heading={result.heading_path}")
        if result.candidates:
            print("candidates:", result.candidates)
        if result.text:
            print("---")
            print(result.text)
    return 0 if result.status == "resolved" else 1


def _normalize_source_key(entry: dict) -> str:
    url = entry.get("source_url")
    if url:
        p = urllib.parse.urlparse(url.strip().lower())
        netloc = p.netloc[4:] if p.netloc.startswith("www.") else p.netloc
        path = p.path.rstrip("/")
        return f"url:{netloc}{path}"
    title = entry.get("title") or entry.get("path") or ""
    return "title:" + re.sub(r"\s+", " ", title.strip().lower())


def cmd_dedup_sources(args, profile) -> int:
    sources = json.loads(Path(args.sources).read_text(encoding="utf-8"))
    groups: dict = {}
    for entry in sources:
        key = _normalize_source_key(entry)
        groups.setdefault(key, []).append(entry)
    result = [
        {
            "key": key,
            "confirmed_same_source": key.startswith("url:"),
            "count": len(items),
            "items": items,
        }
        for key, items in groups.items()
        if len(items) > 1
    ]
    payload = {"total_sources": len(sources), "duplicate_groups": result}
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        if not result:
            print("Повторяющихся первоисточников не найдено.")
        for g in result:
            certainty = "подтверждено (тот же URL)" if g["confirmed_same_source"] else "эвристика по названию — проверить вручную"
            print(f"\n**Один первоисточник** ({certainty}), {g['count']} заметок:")
            for it in g["items"]:
                print(f"- {it.get('path') or it.get('title')}")
    return 0


def cmd_validate(args, profile) -> int:
    evidence = json.loads(Path(args.evidence).read_text(encoding="utf-8"))
    results = []
    ok_count = 0
    for i, item in enumerate(evidence):
        path = item.get("path")
        heading = item.get("heading")
        claim = item.get("claim", f"item[{i}]")
        if not path:
            results.append({"claim": claim, "status": "missing_path"})
            continue
        fr = md.read_fragment(profile.vault_path, path, heading)
        entry = {
            "claim": claim,
            "path": path,
            "heading": heading,
            "status": fr.status,
        }
        if fr.status == "needs_context":
            entry["candidates"] = fr.candidates
        if fr.status == "resolved":
            ok_count += 1
        results.append(entry)
    payload = {
        "total": len(evidence),
        "resolved": ok_count,
        "unresolved": len(evidence) - ok_count,
        "all_grounded": ok_count == len(evidence),
        "results": results,
    }
    if args.format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(f"Проверено {len(evidence)} оснований: {ok_count} подтверждены, {len(evidence) - ok_count} требуют исправления.\n")
        for r in results:
            if r["status"] != "resolved":
                print(f"⚠️ [{r['status']}] «{r['claim']}» → `{r.get('path')}` "
                      f"{('#' + r['heading']) if r.get('heading') else ''} "
                      f"{r.get('candidates', '')}")
    return 0 if payload["all_grounded"] else 1


RESEARCH_NOTE_TEMPLATE = """---
type: research
status: draft
tags:
{tags_yaml}
created: {created}
updated: {updated}
---

## Суть

{suti}

## Вопрос и охват

{scope}

## Синтез

{synthesis}

## Находки

{findings}

## Сравнение подходов

{comparisons}

## Противоречия

{contradictions}

## Пробелы

{gaps}

## Выводы для базы знаний

{implications}

## Источники

{sources}

## Карта: утверждение → источник → фрагмент → степень подтверждения

{claim_evidence_map}
"""


def _bullets(items: List[str], empty_text: str) -> str:
    if not items:
        return empty_text
    return "\n".join(f"- {i}" for i in items)


def cmd_render(args, profile) -> int:
    data = json.loads(Path(args.findings).read_text(encoding="utf-8"))

    def get(key, default=""):
        return data.get(key, default)

    tags = data.get("tags", ["research"])
    tags_yaml = "\n".join(f"  - {t}" for t in tags) if tags else "  - research"

    claim_rows = data.get("claim_evidence_map", [])
    if claim_rows:
        cem_lines = ["| Утверждение | Источник | Фрагмент | Подтверждение |", "|---|---|---|---|"]
        for row in claim_rows:
            cem_lines.append(
                f"| {row.get('claim','')} | {row.get('source','')} | "
                f"{row.get('fragment','')} | {row.get('directness','')} |"
            )
        cem_text = "\n".join(cem_lines)
    else:
        cem_text = "_не заполнено_"

    note = RESEARCH_NOTE_TEMPLATE.format(
        tags_yaml=tags_yaml,
        created=data.get("created", ""),
        updated=data.get("updated", data.get("created", "")),
        suti=get("suti", "_Двухпредложная суть не заполнена._"),
        scope=get("scope", "_не заполнено_"),
        synthesis=get("synthesis", "_не заполнено_"),
        findings=_bullets(data.get("findings", []), "_не заполнено_"),
        comparisons=get("comparisons", "_не заполнено_"),
        contradictions=_bullets(data.get("contradictions", []), "Не выявлено."),
        gaps=_bullets(data.get("gaps", []), "Не выявлено в рамках охвата."),
        implications=_bullets(data.get("implications", []), "_не заполнено_"),
        sources=_bullets(data.get("sources", []), "_не заполнено_"),
        claim_evidence_map=cem_text,
    )

    if args.out:
        out_path = Path(profile.vault_path) / args.out
        if out_path.exists() and not args.overwrite:
            print(f"error: {out_path} already exists (pass --overwrite to replace)", file=sys.stderr)
            return 2
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(note, encoding="utf-8")
        print(f"written: {args.out} ({len(note)} chars)")
        print("Напоминание: после реальной записи в vault вызвать obsidian-index-sync "
              "(skill 18, ещё не реализован в этом проекте) — иначе явно отметить index_dirty.")
    else:
        print(note)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help="profile file path or registered vault id")
    ap.add_argument("--format", default="md", choices=["md", "json"])
    sub = ap.add_subparsers(dest="command", required=True)

    p_frag = sub.add_parser("fragment", help="addressed read of one heading section")
    p_frag.add_argument("--path", required=True)
    p_frag.add_argument("--heading")

    p_val = sub.add_parser("validate", help="check a claim->evidence JSON map against the live vault")
    p_val.add_argument("--evidence", required=True, help="path to a JSON file: [{claim, path, heading}, ...]")

    p_dedup = sub.add_parser("dedup-sources", help="group evidence items citing the same primary source")
    p_dedup.add_argument("--sources", required=True, help="path to a JSON file: [{path/title, source_url}, ...]")

    p_render = sub.add_parser("render", help="render a findings JSON object into the research-note template")
    p_render.add_argument("--findings", required=True)
    p_render.add_argument("--out", help="vault-relative path to write; omit to print to stdout")
    p_render.add_argument("--overwrite", action="store_true")

    args = ap.parse_args()

    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "fragment":
        return cmd_fragment(args, profile)
    if args.command == "validate":
        return cmd_validate(args, profile)
    if args.command == "dedup-sources":
        return cmd_dedup_sources(args, profile)
    if args.command == "render":
        return cmd_render(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
