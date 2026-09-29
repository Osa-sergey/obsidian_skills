#!/usr/bin/env python3
"""obsidian-qa: narrow QA and insight mining at minimal token cost.

Implements spec passport 17-obsidian-qa.md (US-002). Skills 14/16
(obsidian-retrieve/obsidian-evidence) are not built in this project yet,
so this skill assembles its own narrow pipeline directly, the same way
obsidian-research and obsidian-gap-search already fill equivalent gaps:

    obsidian-search(mode=narrow) -> obsidian-context (only if a hit needs
    its neighbors) -> obsidian-fragment-reader for every addressed read ->
    this script's validate-evidence -> render

What this script actually contributes - the parts that are mechanical, not
judgment:

  budget            - print the connected vault's narrow-mode budget
                       (C4/W4 defaults), so there is a concrete number to
                       stay under before reading anything.
  validate-evidence  - re-resolve every evidence item's citation against
                       the live vault (catches a hallucinated path/heading
                       exactly like obsidian-research's own validator),
                       check any verbatim `quote` actually appears in the
                       resolved fragment, tally how much was actually read
                       against the narrow budget, and report which parts
                       of the question (if given) still have zero
                       evidence - "либо явно обозначенный пробел".
  render             - format the final answer + evidence table + budget
                       report; refuses to render an evidence set that
                       failed validation.

Deciding *what* the answer says, which fragments are worth reading, and
whether this question has outgrown narrow mode and needs to escalate to
obsidian-research(mode=deep) instead - all Claude's judgment, informed by
what this script reports back, not something it decides for you.
"""
from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import markdown as md  # noqa: E402
from obsidian_common.profile import ProfileError, VaultProfile, resolve_profile  # noqa: E402

DIRECTNESS_VALUES = {"direct", "paraphrase", "inferred"}
CONFIDENCE_VALUES = {"high", "medium", "low"}
CHARS_PER_TOKEN_ESTIMATE = 4  # rough, language-mixed heuristic - not a real tokenizer


def _norm(s: str) -> str:
    return unicodedata.normalize("NFC", s.strip()).casefold()


def cmd_budget(args, profile: VaultProfile) -> int:
    limits = profile.limits_narrow
    payload = {
        "mode": "narrow",
        "max_tokens": limits.max_tokens,
        "max_notes": limits.max_notes,
        "max_neighbors": limits.max_neighbors,
        "graph_depth": limits.graph_depth,
        "note": (
            "Stay inside this before reading further. Consistently landing "
            "outside it (more notes, more text, deeper graph) is itself "
            "the signal this question needs obsidian-research(mode=deep) "
            "instead of obsidian-qa, per the passport's own escalation rule."
        ),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0


def _resolve_item(vault_path: Path, item: dict) -> md.FragmentResult:
    kwargs = {}
    if item.get("heading"):
        kwargs["heading_query"] = item["heading"]
    elif item.get("block_id"):
        kwargs["block_id"] = item["block_id"]
    elif item.get("line_range"):
        a, b = item["line_range"]
        kwargs["line_range"] = (a, b)
    return md.read_fragment(vault_path, item.get("path", ""), **kwargs)


def _validate_items(vault_path: Path, items: List[dict]) -> List[dict]:
    issues = []
    for i, item in enumerate(items):
        ref = item.get("question_part", f"item[{i}]")
        if not item.get("path"):
            issues.append({"index": i, "ref": ref, "severity": "error", "message": "missing 'path'"})
            continue
        frag = _resolve_item(vault_path, item)
        if frag.status == "not_found":
            issues.append({"index": i, "ref": ref, "severity": "error",
                            "message": f"citation does not resolve: {item.get('path')} "
                                       f"{item.get('heading') or item.get('block_id') or item.get('line_range') or ''}"})
            continue
        if frag.status == "needs_context":
            issues.append({"index": i, "ref": ref, "severity": "error",
                            "message": f"heading is ambiguous, disambiguate with 'Parent > Child': {frag.candidates}"})
            continue
        quote = item.get("quote")
        if quote and quote.strip() not in (frag.text or ""):
            issues.append({"index": i, "ref": ref, "severity": "error",
                            "message": "'quote' was not found verbatim in the resolved fragment - "
                                       "mis-cited or fabricated; use 'paraphrase' instead if it isn't a real quote"})
        directness = item.get("directness")
        if directness not in DIRECTNESS_VALUES:
            issues.append({"index": i, "ref": ref, "severity": "error",
                            "message": f"'directness' must be one of {sorted(DIRECTNESS_VALUES)}, got {directness!r}"})
        confidence = item.get("confidence")
        if confidence not in CONFIDENCE_VALUES:
            issues.append({"index": i, "ref": ref, "severity": "error",
                            "message": f"'confidence' must be one of {sorted(CONFIDENCE_VALUES)}, got {confidence!r}"})
    return issues


def _budget_tally(vault_path: Path, items: List[dict]) -> dict:
    seen_fragments: Dict[tuple, int] = {}
    notes = set()
    for item in items:
        path = item.get("path")
        if not path:
            continue
        notes.add(path)
        frag = _resolve_item(vault_path, item)
        if frag.status == "resolved" and frag.text is not None:
            key = (path, frag.line_start, frag.line_end)
            seen_fragments[key] = len(frag.text)
    chars_read = sum(seen_fragments.values())
    return {
        "distinct_fragments_read": len(seen_fragments),
        "distinct_notes_touched": len(notes),
        "chars_read": chars_read,
        "approx_tokens_read": chars_read // CHARS_PER_TOKEN_ESTIMATE,
    }


def cmd_validate_evidence(args, profile: VaultProfile) -> int:
    items = json.loads(Path(args.evidence_file).read_text(encoding="utf-8"))
    issues = _validate_items(profile.vault_path, items)
    budget = _budget_tally(profile.vault_path, items)
    limits = profile.limits_narrow
    within_budget = (
        budget["approx_tokens_read"] <= limits.max_tokens
        and budget["distinct_notes_touched"] <= limits.max_notes
    )
    budget.update({
        "max_tokens": limits.max_tokens, "max_notes": limits.max_notes,
        "within_budget": within_budget,
    })

    uncovered_parts = []
    if args.question_parts_file:
        parts = json.loads(Path(args.question_parts_file).read_text(encoding="utf-8"))
        covered = {_norm(i.get("question_part", "")) for i in items if i.get("question_part")}
        uncovered_parts = [p for p in parts if _norm(p) not in covered]

    result = {
        "total_items": len(items),
        "issues": issues,
        "ok": not any(i["severity"] == "error" for i in issues),
        "budget": budget,
        "uncovered_question_parts": uncovered_parts,
        "escalate_to_deep_research": (not within_budget) or bool(uncovered_parts),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


def cmd_render(args, profile: VaultProfile) -> int:
    items = json.loads(Path(args.evidence_file).read_text(encoding="utf-8"))
    answer = json.loads(Path(args.answer_file).read_text(encoding="utf-8"))

    issues = _validate_items(profile.vault_path, items)
    errors = [i for i in issues if i["severity"] == "error"]
    if errors:
        print("error: evidence fails validation, fix before rendering:", file=sys.stderr)
        for i in errors:
            print(f"  - [{i['ref']}] {i['message']}", file=sys.stderr)
        return 2

    budget = _budget_tally(profile.vault_path, items)
    limits = profile.limits_narrow
    within_budget = (
        budget["approx_tokens_read"] <= limits.max_tokens
        and budget["distinct_notes_touched"] <= limits.max_notes
    )

    lines = []
    if answer.get("question"):
        lines.append(f"### Вопрос\n\n{answer['question']}\n")
    lines.append(f"### Ответ\n\n{answer.get('answer', '')}\n")

    lines.append("### Основания\n")
    lines.append("| Вопрос/утверждение | Источник | Подтверждение | Уверенность |")
    lines.append("|---|---|---|---|")
    for item in items:
        loc = item.get("heading") or item.get("block_id") or str(item.get("line_range", ""))
        lines.append(f"| {item.get('question_part','')} | `{item.get('path','')}`{(' #' + loc) if loc else ''} | "
                      f"{item.get('directness','')} | {item.get('confidence','')} |")
    lines.append("")

    lines.append("### Бюджет чтения\n")
    lines.append(f"Прочитано: {budget['chars_read']} символов (~{budget['approx_tokens_read']} токенов, "
                 f"грубая оценка) из {budget['distinct_fragments_read']} фрагмент(ов), "
                 f"{budget['distinct_notes_touched']} заметок.")
    lines.append(f"Лимит narrow: ~{limits.max_tokens} токенов, ≤{limits.max_notes} заметок. "
                 f"В рамках бюджета: {'да' if within_budget else '**нет**'}.\n")

    if answer.get("limitations"):
        lines.append(f"### Ограничения\n\n{answer['limitations']}\n")

    if not within_budget:
        lines.append("⚠️ Вышли за рамки narrow-бюджета — если это отражает реальную широту вопроса, "
                      "а не разовое исключение, стоит эскалировать в obsidian-research(mode=deep) "
                      "вместо продолжения точечного чтения.\n")

    print("\n".join(lines))
    return 0


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="profile file path or registered vault id")

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    sub.add_parser("budget", help="print the connected vault's narrow-mode budget", parents=[common])

    p_val = sub.add_parser("validate-evidence", help="resolve citations, tally read budget, find uncovered question parts",
                            parents=[common])
    p_val.add_argument("--evidence-file", required=True,
                        help="JSON array of EvidenceItem: {question_part, path, heading|block_id|line_range, "
                             "quote?, paraphrase?, directness, confidence, retrieval_method}")
    p_val.add_argument("--question-parts-file", help="optional JSON array of question-part strings to check coverage against")

    p_render = sub.add_parser("render", help="format the final answer + evidence table + budget report", parents=[common])
    p_render.add_argument("--evidence-file", required=True)
    p_render.add_argument("--answer-file", required=True, help="JSON: {question?, answer, limitations?}")

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "budget":
        return cmd_budget(args, profile)
    if args.command == "validate-evidence":
        return cmd_validate_evidence(args, profile)
    if args.command == "render":
        return cmd_render(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
