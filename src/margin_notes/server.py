"""FastAPI app: browse a folder, render documents with the review overlay, store notes."""

from __future__ import annotations

import html
from importlib.resources import files
from pathlib import Path, PurePosixPath
from urllib.parse import quote, unquote

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response

from . import __version__
from .notes import NoteStore, notes_path
from .render import render_markdown

MARKDOWN = {".md", ".markdown", ".mdown", ".mkd"}
HTML = {".html", ".htm"}
REVIEWABLE = MARKDOWN | HTML
STATIC = {"review.js": "application/javascript", "page.css": "text/css"}
NO_STORE = {"Cache-Control": "no-store"}
OVERLAY_TAG = '<script src="/__review/static/review.js" defer></script>'


def is_reviewable(path: Path) -> bool:
    return path.suffix.lower() in REVIEWABLE


def inject_overlay(page: str) -> str:
    i = page.lower().rfind("</body>")
    return page[:i] + OVERLAY_TAG + page[i:] if i != -1 else page + OVERLAY_TAG


def create_app(root: Path) -> FastAPI:
    root = root.resolve()
    store = NoteStore()
    app = FastAPI(title="margin-notes", version=__version__, docs_url=None, redoc_url=None, openapi_url=None)

    def resolve(rel: str) -> Path:
        """Map a URL path to a file under root. Dotfiles and anything outside root are 404."""
        parts = PurePosixPath(rel.strip("/")).parts
        if any(p.startswith(".") for p in parts):
            raise HTTPException(404)
        target = root.joinpath(*parts).resolve()
        if not target.is_relative_to(root) or not target.exists():
            raise HTTPException(404)
        return target

    def doc_for(doc: str) -> Path:
        target = resolve(unquote(doc))
        if not target.is_file() or not is_reviewable(target):
            raise HTTPException(404, "not a reviewable document")
        return target

    def notes_payload(doc: Path, notes: list) -> dict:
        try:
            content = store.read_file(doc)
        except ValueError:
            content = None
        return {
            "notes": notes,
            "notes_file": notes_path(doc).name,
            "notes_path": str(notes_path(doc)),
            "notes_json": content,
        }

    @app.get("/__review/static/{name}")
    def static(name: str) -> Response:
        if name not in STATIC:
            raise HTTPException(404)
        body = files("margin_notes").joinpath("static", name).read_text(encoding="utf-8")
        return Response(body, media_type=STATIC[name], headers=NO_STORE)

    @app.get("/__review/api/notes")
    def get_notes(doc: str = Query(...)) -> dict:
        path = doc_for(doc)
        try:
            return notes_payload(path, store.read(path))
        except ValueError as e:
            raise HTTPException(500, f"{notes_path(path).name} is not valid JSON: {e}") from e

    @app.put("/__review/api/notes")
    async def put_note(request: Request, doc: str = Query(...)) -> dict:
        path = doc_for(doc)
        try:
            return notes_payload(path, store.upsert(path, await request.json()))
        except ValueError as e:
            raise HTTPException(400, str(e)) from e

    @app.delete("/__review/api/notes/{note_id}")
    def delete_note(note_id: str, doc: str = Query(...)) -> dict:
        path = doc_for(doc)
        return notes_payload(path, store.delete(path, note_id))

    @app.get("/{rel:path}")
    def serve(rel: str, raw: bool = False) -> Response:
        if rel == "favicon.ico" and not (root / rel).is_file():
            return Response(status_code=204)
        target = resolve(rel)
        if target.is_dir():
            if rel and not rel.endswith("/"):
                return RedirectResponse(f"/{quote(rel)}/")
            return HTMLResponse(listing(root, target, store), headers=NO_STORE)
        suffix = target.suffix.lower()
        if not raw and suffix in MARKDOWN:
            text = target.read_text(encoding="utf-8", errors="replace")
            return HTMLResponse(render_markdown(text, target.name), headers=NO_STORE)
        if not raw and suffix in HTML:
            page = target.read_text(encoding="utf-8", errors="replace")
            return HTMLResponse(inject_overlay(page), headers=NO_STORE)
        return FileResponse(target, headers=NO_STORE)

    return app


def listing(root: Path, folder: Path, store: NoteStore) -> str:
    rel = folder.relative_to(root)
    crumbs = [f'<a href="/">{html.escape(root.name or "/")}</a>']
    acc = ""
    for part in rel.parts:
        acc += quote(part) + "/"
        crumbs.append(f'<a href="/{acc}">{html.escape(part)}</a>')

    entries = [p for p in folder.iterdir() if not p.name.startswith(".") and not p.name.endswith(".notes.json")]
    entries.sort(key=lambda p: (not p.is_dir(), not is_reviewable(p), p.name.lower()))
    rows = []
    if rel.parts:
        rows.append('<li class="dir"><a href="../">../</a></li>')
    for p in entries:
        name = html.escape(p.name)
        href = quote(p.name)
        if p.is_dir():
            rows.append(f'<li class="dir"><a href="{href}/">{name}/</a></li>')
        elif is_reviewable(p):
            n = store.count(p)
            badge = f'<span class="badge">{n} note{"s" if n != 1 else ""}</span>' if n else ""
            kind = "md" if p.suffix.lower() in MARKDOWN else "html"
            rows.append(
                f'<li class="doc {kind}"><a href="{href}">{name}</a>{badge}'
                f'<a class="raw" href="{href}?raw=1">raw</a></li>'
            )
        else:
            rows.append(f'<li class="file"><a href="{href}">{name}</a></li>')
    body = "\n".join(rows) or '<li class="empty">Nothing here.</li>'
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(rel.as_posix() if rel.parts else (root.name or "/"))} · margin-notes</title>
<link rel="stylesheet" href="/__review/static/page.css"></head>
<body class="mn-page"><main class="listing">
<nav class="crumbs">{" / ".join(crumbs)}</nav>
<p class="hint">Open a Markdown or HTML document to highlight and comment on it.
Notes save beside each document as <code>&lt;name&gt;.notes.json</code>.</p>
<ul>{body}</ul>
</main></body></html>"""
