#!/usr/bin/env python3
"""obsidian-evidence: turn a CandidateSet (or any set of addressed
fragment requests) into deduplicated, actually-read source fragments, and
validate a claim-by-claim EvidenceItem[] against them before it's
presented as proof of anything.

Implements spec passport 16-obsidian-evidence.md (US-002/US-003). The
fetch/dedup/validate logic lives in lib/obsidian_common/evidence.py; this
script is the CLI surface only.

Subcommands
-----------
  fetch                - resolve a JSON array of {tag, path, heading?,
                          block_id?, line_range?} requests via
                          fragment-reader, deduplicating exact and
                          contained-range repeats.
  fetch-from-candidates - same, but derived automatically from
                          obsidian-retrieve's CandidateSet JSON output -
                          the normal way to start (one request per
                          candidate that has a semantic_match; candidates
                          without one are reported separately since
                          there's no address to derive).
  validate              - mechanical checks on a Claude-authored
                          EvidenceItem[] JSON against a `fetch` output:
                          every fragment_id must be real and resolved,
                          and a directness=direct item's quote must
                          actually appear verbatim in that fragment's
                          text.
  render                - format a validated EvidenceItem[] as the final
                          report, with read_cost computed per item from
                          the actual fragment length.

Claude decides which claim a fragment supports, how direct that support
is, and how confident to be - this script never does; it only fetches
real text and catches an unverifiable "direct quote" before it goes out.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from typing import List

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "lib"))

from obsidian_common import evidence  # noqa: E402
from obsidian_common.profile import ProfileError, resolve_profile  # noqa: E402


def _load_json(path: str):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _fragment_dict(f: evidence.FetchedFragment) -> dict:
    return {
        "fragment_id": f.fragment_id, "status": f.status, "path": f.path,
        "heading_path": f.heading_path, "line_start": f.line_start, "line_end": f.line_end,
        "text": f.text, "content_hash": f.content_hash, "requested_for": f.requested_for,
        "candidates": f.candidates, "read_cost_tokens": evidence.read_cost_tokens(f),
    }


def _print_fragments(fragments: List[evidence.FetchedFragment], fmt: str, extra: dict = None) -> int:
    unresolved = [f for f in fragments if f.status != "resolved"]
    if fmt == "json":
        out = {"fragments": [_fragment_dict(f) for f in fragments]}
        if extra:
            out.update(extra)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return 1 if unresolved else 0
    for f in fragments:
        print(f"[{f.status}] {f.path}  requested_for={f.requested_for}")
        if f.status == "resolved":
            hp = " > ".join(f.heading_path) if f.heading_path else "(article root)"
            print(f"    fragment_id={f.fragment_id}  {hp}  lines {f.line_start}-{f.line_end}  "
                  f"~{evidence.read_cost_tokens(f)} tokens")
            print(f"    {(f.text or '')[:150]}")
        elif f.candidates:
            print(f"    candidates: {f.candidates}")
        print()
    if unresolved:
        print(f"⚠️ {len(unresolved)} request(s) did not resolve - see status above.")
    return 1 if unresolved else 0


def cmd_fetch(args, profile) -> int:
    raw = _load_json(args.addresses_file)
    requests = [
        evidence.FragmentRequest(
            tag=r["tag"], path=r["path"], heading=r.get("heading"), block_id=r.get("block_id"),
            line_range=tuple(r["line_range"]) if r.get("line_range") else None,
            include_children=r.get("include_children", False), child_depth=r.get("child_depth", 1),
        )
        for r in raw
    ]
    fragments = evidence.fetch_fragments(profile, requests)
    return _print_fragments(fragments, args.format)


def cmd_fetch_from_candidates(args, profile) -> int:
    candidates = _load_json(args.candidates_file).get("candidates", [])
    requests = []
    no_address = []
    for c in candidates:
        m = c.get("semantic_match")
        if not m:
            no_address.append(c["source_path"])
            continue
        if m["node_level"] in ("chunk", "callout"):
            requests.append(evidence.FragmentRequest(
                tag=c["source_path"], path=c["source_path"],
                line_range=(m["line_start"], m["line_end"]),
            ))
        elif m["node_level"] in ("section", "subsection"):
            requests.append(evidence.FragmentRequest(
                tag=c["source_path"], path=c["source_path"],
                heading=" > ".join(m["heading_path"]), include_children=True,
            ))
        else:  # article - whole file
            requests.append(evidence.FragmentRequest(tag=c["source_path"], path=c["source_path"]))
    fragments = evidence.fetch_fragments(profile, requests)
    return _print_fragments(fragments, args.format, extra={"no_addressed_node": no_address})


def cmd_validate(args, profile) -> int:
    fetched_raw = _load_json(args.fetched_file).get("fragments", [])
    fetched = [
        evidence.FetchedFragment(
            fragment_id=f["fragment_id"], status=f["status"], path=f["path"],
            heading_path=f.get("heading_path"), line_start=f.get("line_start"), line_end=f.get("line_end"),
            text=f.get("text"), content_hash=f.get("content_hash"), requested_for=f.get("requested_for", []),
        )
        for f in fetched_raw
    ]
    items = _load_json(args.evidence_file)
    errors = evidence.validate_evidence_items(fetched, items)
    if args.format == "json":
        print(json.dumps({"errors": [asdict(e) for e in errors], "valid": not errors}, ensure_ascii=False, indent=2))
        return 1 if errors else 0
    if not errors:
        print(f"✓ all {len(items)} evidence item(s) valid.")
        return 0
    for e in errors:
        print(f"item[{e.index}].{e.field}: {e.message}")
    return 1


def cmd_render(args, profile) -> int:
    fetched_raw = _load_json(args.fetched_file).get("fragments", [])
    fetched = [
        evidence.FetchedFragment(
            fragment_id=f["fragment_id"], status=f["status"], path=f["path"],
            heading_path=f.get("heading_path"), line_start=f.get("line_start"), line_end=f.get("line_end"),
            text=f.get("text"), content_hash=f.get("content_hash"), requested_for=f.get("requested_for", []),
        )
        for f in fetched_raw
    ]
    by_id = {f.fragment_id: f for f in fetched}
    items = _load_json(args.evidence_file)
    errors = evidence.validate_evidence_items(fetched, items)

    rendered = []
    for item in items:
        f = by_id.get(item.get("fragment_id"))
        rendered.append({
            **item,
            "path": f.path if f else None,
            "heading_path": f.heading_path if f else None,
            "read_cost_tokens": evidence.read_cost_tokens(f) if f else 0,
        })

    if args.format == "json":
        print(json.dumps({
            "evidence": rendered, "validation_errors": [asdict(e) for e in errors],
            "total_read_cost_tokens": sum(r["read_cost_tokens"] for r in rendered),
        }, ensure_ascii=False, indent=2))
        return 1 if errors else 0

    if errors:
        print(f"⚠️ {len(errors)} validation error(s) - fix before treating this as final evidence:\n")
        for e in errors:
            print(f"  item[{e.index}].{e.field}: {e.message}")
        print()
    for i, r in enumerate(rendered):
        hp = " > ".join(r["heading_path"]) if r.get("heading_path") else "(article root)"
        print(f"### {i+1}. {r.get('claim', '(no claim)')}")
        print(f"- file: `{r.get('path')}`  {hp}")
        print(f"- directness: {r.get('directness')}  confidence: {r.get('confidence')}  "
              f"~{r['read_cost_tokens']} tokens")
        if r.get("quote"):
            print(f"- quote: \"{r['quote']}\"")
        if r.get("paraphrase"):
            print(f"- paraphrase: {r['paraphrase']}")
        if r.get("retrieval_methods"):
            print(f"- found via: {r['retrieval_methods']}")
        print()
    print(f"Total read cost: {sum(r['read_cost_tokens'] for r in rendered)} tokens across {len(rendered)} item(s).")
    return 1 if errors else 0


def main() -> int:
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--profile", help="profile file path or registered vault id")
    common.add_argument("--format", default="md", choices=["md", "json"])

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)

    p_fetch = sub.add_parser("fetch", help="resolve addressed requests, deduplicated", parents=[common])
    p_fetch.add_argument("--addresses-file", required=True, help="JSON array of {tag, path, heading?, block_id?, line_range?}")

    p_fc = sub.add_parser("fetch-from-candidates", help="derive requests from obsidian-retrieve's CandidateSet JSON", parents=[common])
    p_fc.add_argument("--candidates-file", required=True, help="obsidian-retrieve search --format json output")

    p_val = sub.add_parser("validate", help="mechanical checks on a Claude-authored EvidenceItem[] JSON", parents=[common])
    p_val.add_argument("--evidence-file", required=True)
    p_val.add_argument("--fetched-file", required=True, help="a `fetch`/`fetch-from-candidates` --format json output")

    p_render = sub.add_parser("render", help="format the final EvidenceItem[] report", parents=[common])
    p_render.add_argument("--evidence-file", required=True)
    p_render.add_argument("--fetched-file", required=True)

    args = ap.parse_args()
    try:
        profile = resolve_profile(explicit=args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.command == "fetch":
        return cmd_fetch(args, profile)
    if args.command == "fetch-from-candidates":
        return cmd_fetch_from_candidates(args, profile)
    if args.command == "validate":
        return cmd_validate(args, profile)
    if args.command == "render":
        return cmd_render(args, profile)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
