"""The `<document>.notes.json` file that sits beside each reviewed document."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

ABOUT = (
    "Review notes on {doc}. Notes are in document order. Each note has `quote` (the "
    "highlighted text, whitespace collapsed), `section` (the nearest heading before it), "
    "and `comment` (the reviewer's remark; may be empty for a bare highlight). A note "
    "with a null `quote` is a general comment on the whole document. `anchor` holds the "
    "exact text and surrounding context used to re-find the highlight. If "
    "`document_sha256` no longer matches the file, the document changed after review."
)


def _file_mode() -> int:
    mask = os.umask(0)  # reading the umask means setting it; do it once, at import
    os.umask(mask)
    return 0o666 & ~mask


FILE_MODE = _file_mode()
NOTE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def notes_path(doc: Path) -> Path:
    return doc.with_name(f"{doc.name}.notes.json")


def now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _order(note: dict[str, Any]) -> tuple:
    anchor = note.get("anchor")
    if isinstance(anchor, dict):
        return (1, anchor.get("start") or 0, "")
    return (0, 0, str(note.get("created_at", "")))


def validate(note: Any) -> dict[str, Any]:
    if not isinstance(note, dict) or not isinstance(note.get("id"), str) or not NOTE_ID.match(note["id"]):
        raise ValueError("a note is an object with an `id` of letters, digits, _ or -")
    return {k: v for k, v in note.items() if not k.startswith("_")}


class NoteStore:
    """Read-modify-write under one lock, so concurrent reviewers never clobber each other."""

    def __init__(self) -> None:
        self._lock = threading.Lock()

    def read(self, doc: Path) -> list[dict[str, Any]]:
        path = notes_path(doc)
        if not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        return list(data.get("notes", []))

    def count(self, doc: Path) -> int:
        try:
            return len(self.read(doc))
        except (OSError, ValueError):
            return 0

    def upsert(self, doc: Path, note: dict[str, Any]) -> list[dict[str, Any]]:
        note = validate(note)
        with self._lock:
            notes = [n for n in self.read(doc) if n.get("id") != note["id"]]
            notes.append(note)
            return self._write(doc, notes)

    def delete(self, doc: Path, note_id: str) -> list[dict[str, Any]]:
        with self._lock:
            notes = self.read(doc)
            kept = [n for n in notes if n.get("id") != note_id]
            return self._write(doc, kept) if len(kept) != len(notes) else notes

    def _write(self, doc: Path, notes: list[dict[str, Any]]) -> list[dict[str, Any]]:
        notes.sort(key=_order)
        path = notes_path(doc)
        if not notes and path.exists():
            path.unlink()
            return notes
        data = {
            "about": ABOUT.format(doc=doc.name),
            "document": doc.name,
            "document_path": str(doc),
            "document_sha256": hashlib.sha256(doc.read_bytes()).hexdigest(),
            "updated_at": now(),
            "notes": notes,
        }
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".notes-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                f.write("\n")
            os.chmod(tmp, FILE_MODE)  # mkstemp creates 0600; use ordinary permissions
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
        return notes
