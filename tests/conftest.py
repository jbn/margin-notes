from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from margin_notes.server import create_app

GUIDE_MD = """\
---
title: Front Matter Title
---
# Heading

Inline math $e^{i\\pi} + 1 = 0$ and a table:

| a | b |
|---|---|
| 1 | 2 |

$$
\\int_0^1 x\\,dx
$$

![diagram](img/pic.png)

```python
def f(): return 1
```

```mermaid
graph TD; A-->B
```

> [!WARNING]
> Careful.

- [x] done
"""

PAGE_HTML = "<html><head><title>Page</title></head><body><h1>Hi</h1><p>Text</p></body></html>"


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A small folder: Markdown, HTML, an image, a dotfile, a dot-directory and a plain file."""
    (tmp_path / "docs" / "img").mkdir(parents=True)
    (tmp_path / "docs" / "guide.md").write_text(GUIDE_MD, encoding="utf-8")
    (tmp_path / "docs" / "img" / "pic.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "page.html").write_text(PAGE_HTML, encoding="utf-8")
    (tmp_path / "plain.md").write_text("Just text. Costs $5 and $10.\n", encoding="utf-8")
    (tmp_path / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (tmp_path / ".secret").write_text("nope", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("[core]", encoding="utf-8")
    return tmp_path


@pytest.fixture
def client(tree: Path) -> TestClient:
    return TestClient(create_app(tree))


def note(id: str, start: int | None = 0, **kw) -> dict:
    """A note shaped like the browser sends; `start=None` makes a general note."""
    anchor = None if start is None else {"exact": "Careful.", "prefix": "", "suffix": "", "start": start}
    return {
        "id": id,
        "quote": None if start is None else "Careful.",
        "section": None,
        "comment": "",
        "created_at": "2026-01-01T00:00:00-08:00",
        "updated_at": "2026-01-01T00:00:00-08:00",
        "anchor": anchor,
        **kw,
    }
