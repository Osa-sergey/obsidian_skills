"""Omnisearch HTTP client.

Docs: https://publish.obsidian.md/omnisearch/Public+API+%26+URL+Scheme
(confirmed 2026-09-29). Single endpoint:

    GET http://localhost:<port>/search?q=<query>  ->  ResultNoteApi[]

    ResultNoteApi = { score, vault, path, basename, foundWords, matches,
                       excerpt }
    SearchMatchApi = { match, offset }

The server must be turned on in Omnisearch's own settings, only listens on
localhost, stops when Obsidian closes, and is unavailable on mobile - so
"unavailable" is an expected, not exceptional, outcome (S6 default: fall
back to term/filesystem search and say so, do not just fail the request).
"""
from __future__ import annotations

import html
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import List, Optional

_TAG_RE = re.compile(r"<[^>]+>")


def clean_excerpt(text: str) -> str:
    """Omnisearch's `excerpt` is HTML (<br>, entities, possibly <mark>) meant
    for its own UI; unwrap it to plain text for a report/JSON consumer.
    Shared by every skill that surfaces an Omnisearch excerpt directly."""
    if not text:
        return ""
    text = text.replace("<br>", " / ")
    text = _TAG_RE.sub("", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


class OmnisearchUnavailable(RuntimeError):
    """The HTTP server is unreachable, refused, or timed out."""


@dataclass
class SearchMatch:
    match: str
    offset: int


@dataclass
class OmnisearchHit:
    score: float
    vault: str
    path: str
    basename: str
    found_words: List[str]
    matches: List[SearchMatch]
    excerpt: str


class OmnisearchClient:
    def __init__(self, host: str = "localhost", port: int = 51361, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout

    def search(self, query: str, vault_filter: Optional[str] = None) -> List[OmnisearchHit]:
        url = f"http://{self.host}:{self.port}/search?q={urllib.parse.quote(query)}"
        try:
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
        except (urllib.error.URLError, ConnectionError, TimeoutError, OSError) as exc:
            raise OmnisearchUnavailable(
                f"Omnisearch HTTP server not reachable at {self.host}:{self.port} "
                f"({exc}). Enable 'HTTP Server' in Omnisearch settings inside "
                "Obsidian, with the vault open."
            ) from exc

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise OmnisearchUnavailable(
                f"Omnisearch returned non-JSON response: {exc}"
            ) from exc

        hits = [
            OmnisearchHit(
                score=item.get("score", 0.0),
                vault=item.get("vault", ""),
                path=item.get("path", ""),
                basename=item.get("basename", ""),
                found_words=item.get("foundWords", []) or [],
                matches=[
                    SearchMatch(m.get("match", ""), m.get("offset", -1))
                    for m in item.get("matches", []) or []
                ],
                excerpt=item.get("excerpt", ""),
            )
            for item in data
        ]
        if vault_filter:
            hits = [h for h in hits if h.vault == vault_filter]
        return hits

    def ping(self) -> bool:
        try:
            self.search("")
            return True
        except OmnisearchUnavailable:
            return False


def filter_by_vault(hits: List[OmnisearchHit], expected_vault: str) -> "tuple[List[OmnisearchHit], Optional[str]]":
    """Filters hits down to the ones actually reporting `expected_vault`
    (see OmnisearchClient.search - Omnisearch answers for *every* vault
    open in the same Obsidian instance) and flags the case that used to be
    a silent, confusing "nothing found": raw hits existed but every one of
    them reported a different vault name, which almost always means
    `expected_vault` (normally `profile.vault_path.name`, never
    `profile.vault_id` - see the vault_id/vault-name distinction this was
    root-caused from) no longer matches what Obsidian actually reports,
    not that the vault genuinely has no matches. Returns
    (filtered_hits, warning_or_None). Callers with their own merge/ranking
    shape (obsidian-search, obsidian-gap-search) keep their own inline
    version of this same check for now; new callers should use this one
    instead of re-deriving it a third time."""
    filtered = []
    other_vaults_seen: set = set()
    for h in hits:
        if h.vault and h.vault != expected_vault:
            other_vaults_seen.add(h.vault)
            continue
        filtered.append(h)
    warning = None
    if hits and not filtered and other_vaults_seen:
        warning = (
            f"Omnisearch returned {len(hits)} hit(s) but none reported this vault's "
            f"expected name {expected_vault!r} - it reported {sorted(other_vaults_seen)} instead. "
            "The connected vault's folder may have been renamed/moved since it was registered, "
            "or a different vault with overlapping content is what's actually open in Obsidian. "
            "Run bin/obsidian-vault doctor to check the registered vault_path."
        )
    return filtered, warning
