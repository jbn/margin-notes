from __future__ import annotations

import hashlib
import json
import os
import stat
import threading
from pathlib import Path

import pytest

from margin_notes.notes import FILE_MODE, NoteStore, notes_path, validate

from conftest import note


@pytest.fixture
def doc(tmp_path: Path) -> Path:
    p = tmp_path / "report.md"
    p.write_text("# Report\n\nCareful.\n", encoding="utf-8")
    return p


@pytest.fixture
def store() -> NoteStore:
    return NoteStore()


def saved(doc: Path) -> dict:
    return json.loads(notes_path(doc).read_text(encoding="utf-8"))


def test_notes_path_keeps_the_full_name(tmp_path):
    assert notes_path(tmp_path / "a.md").name == "a.md.notes.json"
    assert notes_path(tmp_path / "a.html").name == "a.html.notes.json"


class TestValidate:
    @pytest.mark.parametrize("bad", [None, [], "x", {}, {"id": 3}, {"id": ""}, {"id": "../x"}, {"id": "a" * 65}])
    def test_rejects(self, bad):
        with pytest.raises(ValueError):
            validate(bad)

    def test_strips_client_only_fields(self):
        assert validate({"id": "a-1_B", "_orphan": True, "comment": "c"}) == {"id": "a-1_B", "comment": "c"}


class TestStore:
    def test_read_missing_is_empty(self, store, doc):
        assert store.read(doc) == []
        assert store.count(doc) == 0

    def test_file_contents(self, store, doc):
        store.upsert(doc, note("a"))
        data = saved(doc)
        assert data["document"] == "report.md"
        assert data["document_path"] == str(doc)
        assert data["document_sha256"] == hashlib.sha256(doc.read_bytes()).hexdigest()
        assert "report.md" in data["about"]
        assert data["updated_at"][-6] in "+-"  # local time with a UTC offset
        assert [n["id"] for n in data["notes"]] == ["a"]

    def test_order_is_general_first_then_document_order(self, store, doc):
        store.upsert(doc, note("late", start=90))
        store.upsert(doc, note("g2", start=None, created_at="2026-01-02T00:00:00-08:00"))
        store.upsert(doc, note("early", start=5))
        store.upsert(doc, note("g1", start=None, created_at="2026-01-01T00:00:00-08:00"))
        assert [n["id"] for n in store.read(doc)] == ["g1", "g2", "early", "late"]

    def test_upsert_replaces_by_id(self, store, doc):
        store.upsert(doc, note("a", comment="first"))
        store.upsert(doc, note("a", comment="second"))
        assert [(n["id"], n["comment"]) for n in store.read(doc)] == [("a", "second")]

    def test_delete(self, store, doc):
        store.upsert(doc, note("a"))
        store.upsert(doc, note("b", start=9))
        assert [n["id"] for n in store.delete(doc, "a")] == ["b"]
        assert store.count(doc) == 1

    def test_delete_unknown_id_does_not_rewrite(self, store, doc):
        store.upsert(doc, note("a"))
        before = notes_path(doc).stat().st_mtime_ns
        assert [n["id"] for n in store.delete(doc, "zzz")] == ["a"]
        assert notes_path(doc).stat().st_mtime_ns == before

    def test_deleting_the_last_note_removes_the_file(self, store, doc):
        store.upsert(doc, note("a"))
        store.delete(doc, "a")
        assert not notes_path(doc).exists()

    def test_unicode_is_written_readably(self, store, doc):
        store.upsert(doc, note("a", comment="naïve — 日本語"))
        assert "naïve — 日本語" in notes_path(doc).read_text(encoding="utf-8")

    def test_no_temp_files_left_behind(self, store, doc):
        for i in range(5):
            store.upsert(doc, note(f"n{i}", start=i))
        assert sorted(p.name for p in doc.parent.iterdir()) == ["report.md", "report.md.notes.json"]

    @pytest.mark.skipif(os.name == "nt", reason="POSIX permissions")
    def test_file_gets_ordinary_permissions(self, store, doc):
        store.upsert(doc, note("a"))
        assert stat.S_IMODE(notes_path(doc).stat().st_mode) == FILE_MODE

    def test_corrupt_file(self, store, doc):
        notes_path(doc).write_text("{not json", encoding="utf-8")
        assert store.count(doc) == 0
        with pytest.raises(ValueError):
            store.read(doc)

    def test_reads_files_from_the_single_file_version(self, store, doc):
        # Notes written by the original single-file script have the same shape.
        notes_path(doc).write_text(json.dumps({"document": "report.md", "notes": [note("old")]}), encoding="utf-8")
        store.upsert(doc, note("new", start=50))
        assert [n["id"] for n in store.read(doc)] == ["old", "new"]

    def test_concurrent_writers_lose_nothing(self, store, doc):
        threads = [threading.Thread(target=store.upsert, args=(doc, note(f"t{i}", start=i))) for i in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert store.count(doc) == 40
