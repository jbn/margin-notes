from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from margin_notes.server import OVERLAY_TAG, create_app, inject_overlay

from conftest import GUIDE_MD, PAGE_HTML, note

API = "/__review/api/notes"


class TestInjectOverlay:
    def test_before_closing_body(self):
        assert inject_overlay("<html><body>x</body></html>") == f"<html><body>x{OVERLAY_TAG}</body></html>"

    def test_uses_the_last_body_tag_case_insensitively(self):
        page = "<BODY><pre>&lt;/body&gt; </body> in text</pre></BODY>"
        assert inject_overlay(page).endswith(f"{OVERLAY_TAG}</BODY>")

    def test_appends_when_there_is_no_body(self):
        assert inject_overlay("<p>fragment</p>") == f"<p>fragment</p>{OVERLAY_TAG}"


class TestListing:
    def test_root(self, client):
        r = client.get("/")
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-store"
        t = r.text
        # Folders, then documents, then other files.
        assert t.index('href="docs/"') < t.index('href="page.html"') < t.index('href="data.csv"')
        assert 'href="page.html?raw=1"' in t
        assert ".secret" not in t and ".git" not in t
        assert 'href="../"' not in t

    def test_subfolder_has_breadcrumbs_and_parent(self, client, tree):
        t = client.get("/docs/").text
        assert f'>{tree.name}</a> / <a href="/docs/">docs</a>' in t
        assert 'href="../"' in t
        assert 'href="guide.md"' in t

    def test_folder_without_slash_redirects(self, client):
        r = client.get("/docs", follow_redirects=False)
        assert r.status_code == 307
        assert r.headers["location"] == "/docs/"

    def test_note_counts_and_hidden_notes_files(self, client):
        client.put(API, params={"doc": "/page.html"}, json=note("a"))
        t = client.get("/").text
        assert '<span class="badge">1 note</span>' in t
        assert "page.html.notes.json" not in t
        client.put(API, params={"doc": "/page.html"}, json=note("b", start=5))
        assert '<span class="badge">2 notes</span>' in client.get("/").text

    def test_awkward_names_are_escaped_and_quoted(self, client, tree):
        # Spaces, #, &, quotes and brackets: all legal filenames on Windows too.
        (tree / "a #1 & 'c' [x].md").write_text("# x\n", encoding="utf-8", newline="\n")
        t = client.get("/").text
        assert 'href="a%20%231%20%26%20%27c%27%20%5Bx%5D.md"' in t
        assert ">a #1 &amp; &#x27;c&#x27; [x].md<" in t
        assert client.get("/a%20%231%20%26%20%27c%27%20%5Bx%5D.md").status_code == 200

    def test_empty_folder(self, client, tree):
        (tree / "empty").mkdir()
        assert "../" in client.get("/empty/").text


class TestDocuments:
    def test_markdown_is_rendered_with_the_overlay(self, client):
        r = client.get("/docs/guide.md")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert "<title>Front Matter Title</title>" in r.text
        assert "/__review/static/review.js" in r.text

    def test_markdown_raw(self, client):
        assert client.get("/docs/guide.md?raw=1").text == GUIDE_MD

    @pytest.mark.parametrize("name", ["x.markdown", "x.MD", "x.mdown", "x.mkd"])
    def test_markdown_extensions(self, client, tree, name):
        (tree / name).write_text("# Ext\n", encoding="utf-8", newline="\n")
        assert "<title>Ext</title>" in client.get(f"/{name}").text

    def test_html_gets_the_overlay(self, client):
        assert client.get("/page.html").text == inject_overlay(PAGE_HTML)

    def test_html_raw_is_untouched(self, client):
        assert client.get("/page.html?raw=1").text == PAGE_HTML

    def test_htm(self, client, tree):
        (tree / "old.htm").write_text(PAGE_HTML, encoding="utf-8", newline="\n")
        assert OVERLAY_TAG in client.get("/old.htm").text

    def test_relative_assets_are_served(self, client):
        assert client.get("/docs/img/pic.png").content == b"\x89PNG fake"
        assert client.get("/data.csv").text == "a,b\n1,2\n"

    def test_invalid_utf8_does_not_crash(self, client, tree):
        (tree / "latin.md").write_bytes("# Caf\xe9\n".encode("latin-1"))
        assert client.get("/latin.md").status_code == 200

    def test_favicon_is_quiet(self, client, tree):
        assert client.get("/favicon.ico").status_code == 204
        (tree / "favicon.ico").write_bytes(b"ico")
        assert client.get("/favicon.ico").content == b"ico"


class TestStatic:
    @pytest.mark.parametrize(("name", "kind"), [("review.js", "javascript"), ("page.css", "text/css")])
    def test_bundled(self, client, name, kind):
        r = client.get(f"/__review/static/{name}")
        assert r.status_code == 200
        assert kind in r.headers["content-type"]

    def test_only_bundled_files(self, client):
        assert client.get("/__review/static/__init__.py").status_code == 404
        assert client.get("/__review/static/..%2F__init__.py").status_code == 404


class TestConfinement:
    @pytest.mark.parametrize(
        "path",
        [
            "/.secret",
            "/.git/config",
            "/docs/../.secret",
            "/%2e%2e/%2e%2e/etc/passwd",
            "/..%2f..%2fetc%2fpasswd",
            "/missing.md",
        ],
    )
    def test_not_found(self, client, path):
        assert client.get(path).status_code == 404

    @pytest.mark.skipif(os.name == "nt", reason="symlinks need privileges on Windows")
    def test_symlinks_out_of_root_are_blocked(self, tmp_path):
        root, outside = tmp_path / "root", tmp_path / "outside.md"
        root.mkdir()
        outside.write_text("# secret\n", encoding="utf-8", newline="\n")
        (root / "link.md").symlink_to(outside)
        (root / "inside.md").write_text("# ok\n", encoding="utf-8", newline="\n")
        (root / "alias.md").symlink_to(root / "inside.md")
        c = TestClient(create_app(root))
        assert c.get("/link.md").status_code == 404
        assert c.get("/alias.md").status_code == 200


class TestNotesApi:
    def test_roundtrip(self, client, tree):
        doc = {"doc": "/docs/guide.md"}
        r = client.get(API, params=doc)
        assert r.json() == {"notes": [], "notes_file": "guide.md.notes.json"}

        r = client.put(API, params=doc, json=note("a", comment="why?", _orphan=True))
        assert r.status_code == 200
        assert r.json()["notes"][0]["comment"] == "why?"

        on_disk = json.loads((tree / "docs" / "guide.md.notes.json").read_text(encoding="utf-8"))
        assert "_orphan" not in on_disk["notes"][0]

        r = client.delete(f"{API}/a", params=doc)
        assert r.json()["notes"] == []
        assert not (tree / "docs" / "guide.md.notes.json").exists()

    def test_doc_param_is_percent_encoded_path(self, client, tree):
        (tree / "my doc.md").write_text("# x\n", encoding="utf-8", newline="\n")
        assert client.put(API, params={"doc": "/my%20doc.md"}, json=note("a")).status_code == 200
        assert (tree / "my doc.md.notes.json").exists()

    def test_put_returns_other_reviewers_notes(self, client):
        doc = {"doc": "/page.html"}
        client.put(API, params=doc, json=note("theirs"))
        ids = [n["id"] for n in client.put(API, params=doc, json=note("mine", start=5)).json()["notes"]]
        assert ids == ["theirs", "mine"]

    @pytest.mark.parametrize("doc", ["/data.csv", "/docs/img/pic.png", "/docs/", "/.secret", "/nope.md", "/../x.md"])
    def test_only_reviewable_documents(self, client, doc):
        assert client.get(API, params={"doc": doc}).status_code == 404
        assert client.put(API, params={"doc": doc}, json=note("a")).status_code == 404

    def test_doc_param_required(self, client):
        assert client.get(API).status_code == 422

    @pytest.mark.parametrize("body", [{"id": "../x"}, {"no": "id"}, [1, 2]])
    def test_bad_note(self, client, body):
        assert client.put(API, params={"doc": "/page.html"}, json=body).status_code == 400

    def test_malformed_json(self, client):
        headers = {"content-type": "application/json"}
        r = client.put(API, params={"doc": "/page.html"}, content=b"{nope", headers=headers)
        assert r.status_code == 400

    def test_corrupt_notes_file_is_reported(self, client, tree: Path):
        (tree / "page.html.notes.json").write_text("{bad", encoding="utf-8", newline="\n")
        r = client.get(API, params={"doc": "/page.html"})
        assert r.status_code == 500
        assert "page.html.notes.json is not valid JSON" in r.json()["detail"]
