# margin-notes

Review HTML and Markdown documents in your browser. Select a passage, leave a comment, and the
notes save as JSON next to the document, ready for a person or an LLM agent to act on.

It replaces `python -m http.server` when the reason you're serving a folder is to read and
critique what's in it.

```sh
uvx margin-notes                     # browse the current folder
uvx margin-notes docs/design.md      # open one document
uvx margin-notes ~/reports --host 0.0.0.0 --port 9000
```

## What it does

- **Any folder.** A listing shows Markdown and HTML documents first, with a count of the notes on each.
  Other files (images, PDFs, data) are served as-is, so relative links and images work.
- **HTML** is served unchanged with a small review overlay added. Its own scripts and styles still run.
- **Markdown** is rendered GitHub-style: tables, task lists, footnotes, definition lists, heading
  anchors, front matter (`title:` becomes the page title), alerts (`> [!NOTE]`, `[!TIP]`,
  `[!IMPORTANT]`, `[!WARNING]`, `[!CAUTION]`), Pygments syntax highlighting, light and dark themes.
  - **Math** with MathJax: `$inline$`, `$$display$$` and ```` ```math ```` fences. MathJax only
    loads on pages that contain math, so prices like `$5 and $10` are left alone.
  - **Diagrams** in ```` ```mermaid ```` fences.
  - Add `?raw=1` to any document URL to get the source.
- **Reviewing:** select text and click **💬 Comment**. ⌘↵ saves and Esc cancels. Click a highlight to
  edit or delete it. **Notes** (bottom right) lists every note in document order and has
  **+ General note** for comments about the whole document. Every change saves immediately.

MathJax and mermaid load from jsDelivr, so math and diagrams need internet access. Everything
else works offline.

## The notes file

`report.md` gets `report.md.notes.json` beside it. Using the full filename keeps `report.md` and
`report.html` in one folder from sharing a file.

```json
{
  "about": "Review notes on report.md. Notes are in document order. ...",
  "document": "report.md",
  "document_path": "/abs/path/report.md",
  "document_sha256": "…",
  "updated_at": "2026-11-17T13:43:20-08:00",
  "notes": [
    {
      "id": "nmwl7ygt5zh7r",
      "quote": "links five constants",
      "section": "Euler and friends",
      "comment": "which five?",
      "created_at": "2026-11-17T13:43:19-08:00",
      "updated_at": "2026-11-17T13:43:20-08:00",
      "anchor": { "exact": "links five constants", "prefix": "…", "suffix": "…", "start": 35 }
    }
  ]
}
```

- `quote` is the highlighted text and `section` is the nearest heading above it. A note with a
  null `quote` is a general comment.
- `anchor` re-finds the highlight using the exact text and its surroundings. A highlight whose
  text has since been edited out shows as **not found** in the notes panel.
- `about` describes the format in plain words, so an agent handed the file needs no other
  instructions.
- If `document_sha256` no longer matches the file, the document changed after the review.
- Deleting the last note removes the file.

Several people can review the same document at once. Each save changes one note on the server,
so reviewers don't overwrite each other.

## Options

```
margin-notes [PATH] [--host HOST] [-p PORT] [--no-open] [--version]
```

| Option | Default | |
|---|---|---|
| `PATH` | `.` | A folder to browse, or a document to open |
| `--host` | `127.0.0.1` | `0.0.0.0` makes it reachable from your network |
| `-p`, `--port` | `8765` | The first port to try; it moves up if that one is busy |
| `--no-open` | | Don't open a browser |

**Security:** there is no authentication. Bound to anything other than localhost, anyone who can
reach the port can read every file under the folder and add notes. Dotfiles and dot-directories
(`.git`, `.env`) are never served, and nothing outside the folder is reachable, including
through symlinks.

## Development

```sh
uv sync --all-groups
uv run pytest                     # unit tests, plus browser tests when Playwright has a browser
uv run playwright install chromium  # once, if you have no Chrome or Chromium
uv run pytest -m "not browser"    # skip the browser tests
uv run ruff check && uv run ruff format --check
uv run margin-notes .             # try it on this repository
```

The browser tests (`tests/test_browser.py`) drive the overlay in Chromium through Playwright:
selecting text, anchoring repeated phrases, editing, deleting, general notes, and highlights
that no longer match. They need no network.

### Releasing

1. Bump `__version__` in `src/margin_notes/__init__.py` and add a section to `CHANGELOG.md`.
2. Commit, then tag and push: `git tag v0.1.0 && git push --tags`.
3. `.github/workflows/release.yml` checks that the tag matches the version, runs the tests,
   builds, and publishes to PyPI through a trusted publisher. Set that up once at
   <https://pypi.org/manage/account/publishing/> with workflow `release.yml` and environment `pypi`.

To publish from your own machine instead, run `uv build && uv publish`.
