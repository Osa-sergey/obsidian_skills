"""Low-level, dependency-free write primitives that `patch.py` builds on.

Kept separate from `patch.py` (the propose/apply *policy*) so the raw
mechanics - atomic write, diff, hashing, id generation - are each one
obvious, independently testable function.
"""
from __future__ import annotations

import difflib
import os
import tempfile
import uuid
from pathlib import Path

from .markdown import content_hash


def region_hash(text: str) -> str:
    """Alias of markdown.content_hash, named for what patch.py uses it for:
    hashing whatever *region* (section/block/line/frontmatter) a patch
    touches, not necessarily a whole file."""
    return content_hash(text)


def new_change_id() -> str:
    return uuid.uuid4().hex[:12]


def make_diff(old_text: str, new_text: str, label: str) -> str:
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = difflib.unified_diff(
        old_lines, new_lines, fromfile=f"{label} (before)", tofile=f"{label} (after)"
    )
    return "".join(diff)


def atomic_write(path: Path, content: str) -> None:
    """Write via a temp file + rename so a crash mid-write can never leave a
    half-written note on disk - the rename is atomic on the same filesystem,
    which a temp file in the target's own directory guarantees."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
