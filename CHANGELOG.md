# Changelog

## 0.1.0 (2026-11-18)

First release.

- Browse a folder or open a single document; Markdown and HTML get a review overlay.
- Highlight passages and comment on them, or add general notes. Notes save immediately to
  `<document>.notes.json` beside each document, in document order, with a plain-language
  `about` field describing the format.
- Markdown rendering: GitHub-flavoured tables, task lists, footnotes, definition lists, alerts,
  heading anchors, front-matter titles, Pygments highlighting, light and dark themes, MathJax
  math and mermaid diagrams.
- `--host` to bind beyond localhost (with a warning), `--port` with automatic fallback.
- Dotfiles and paths outside the served folder are never served.
