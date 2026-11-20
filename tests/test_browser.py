"""End-to-end tests of the review overlay in a real browser.

Run with `uv run --group browser pytest -m browser`. They skip when Playwright or a browser is
missing. Pages here avoid math and mermaid so the tests need no network.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import pytest
import uvicorn

from margin_notes.cli import free_port
from margin_notes.server import create_app

sync_api = pytest.importorskip("playwright.sync_api")
pytestmark = pytest.mark.browser

ARTICLE = """<!doctype html><html><head><title>Article</title></head><body>
<h1>Article</h1>
<h2>Methods</h2>
<p id="p1">We measured alpha <b>beta</b> gamma across the corpus.</p>
<p id="p2">The same phrase appears twice. The same phrase appears twice.</p>
<svg width="200" height="40"><text x="0" y="20">svg label text</text></svg>
<h2>Results</h2>
<p id="p3">Rejection rose from 12% to 47% on held-out data.</p>
<script>window.pageKeys = 0; document.addEventListener("keydown", () => window.pageKeys++);</script>
</body></html>"""

SELECT = """([id, needle, nth]) => {
  const el = id ? document.getElementById(id) : document.body;
  const w = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  let text = "", nodes = [];
  for (let n; (n = w.nextNode()); ) { nodes.push([n, text.length]); text += n.data; }
  let at = -1;
  for (let k = 0; k <= nth; k++) at = text.indexOf(needle, at + 1);
  if (at < 0) return false;
  const point = (off) => { for (const [n, s] of nodes) if (off <= s + n.data.length) return [n, off - s]; };
  const r = document.createRange();
  r.setStart(...point(at)); r.setEnd(...point(at + needle.length));
  const sel = getSelection(); sel.removeAllRanges(); sel.addRange(r);
  document.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
  return true;
}"""


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        for launch in (lambda: p.chromium.launch(channel="chrome"), p.chromium.launch):
            try:
                b = launch()
                break
            except Exception:
                continue
        else:
            pytest.skip("no Chromium available (try: uv run --group browser playwright install chromium)")
        yield b
        b.close()


@pytest.fixture
def site(tmp_path: Path) -> Iterator[tuple[str, Path]]:
    (tmp_path / "article.html").write_text(ARTICLE, encoding="utf-8", newline="\n")
    readme = "# Readme\n\nInstall it with **uv** and run it.\n"
    (tmp_path / "readme.md").write_text(readme, encoding="utf-8", newline="\n")
    port = free_port("127.0.0.1", 18765)
    server = uvicorn.Server(uvicorn.Config(create_app(tmp_path), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    yield f"http://127.0.0.1:{port}/", tmp_path
    server.should_exit = True
    thread.join(timeout=5)


@pytest.fixture
def page(browser):
    pg = browser.new_page()
    errors: list[str] = []
    pg.on("pageerror", lambda e: errors.append(str(e)))
    yield pg
    pg.close()
    assert errors == []


def open_doc(page, url: str) -> None:
    page.goto(url)
    page.wait_for_function("document.querySelector('#__review-host') && window.__marginNotes")
    page.wait_for_timeout(300)  # boot fetches notes after load


def ui(page, selector: str):
    return page.locator("#__review-host").locator(selector)


def comment(page, needle: str, text: str, *, el: str | None = None, nth: int = 0) -> None:
    assert page.evaluate(SELECT, [el, needle, nth]), f"{needle!r} not found"
    ui(page, "#add").click()
    ui(page, "textarea").fill(text)
    ui(page, ".save").click()
    page.wait_for_function(
        "document.querySelector('#__review-host').shadowRoot.querySelector('.status').textContent.startsWith('Saved')"
    )


def marks(page) -> list[str]:
    return page.evaluate("[...document.querySelectorAll('mark.__rv')].map(m => m.textContent)")


def saved(root: Path, name: str) -> list[dict]:
    return json.loads((root / f"{name}.notes.json").read_text(encoding="utf-8"))["notes"]


def test_comment_saves_and_survives_reload(site, page):
    url, root = site
    open_doc(page, url + "article.html")
    comment(page, "Rejection rose from 12% to 47%", "In-sample or held out?")

    [n] = saved(root, "article.html")
    assert n["quote"] == "Rejection rose from 12% to 47%"
    assert n["section"] == "Results"
    assert n["comment"] == "In-sample or held out?"
    assert n["anchor"]["exact"] == n["quote"]
    assert n["created_at"][-6] in "+-"

    page.reload()
    open_doc(page, url + "article.html")
    assert marks(page) == ["Rejection rose from 12% to 47%"]
    assert ui(page, "#toggle").text_content() == "Notes · 1"


def test_selection_across_inline_elements(site, page):
    url, root = site
    open_doc(page, url + "article.html")
    comment(page, "alpha beta gamma", "spans a <b>", el="p1")
    assert "".join(marks(page)) == "alpha beta gamma"
    assert len(marks(page)) == 3  # one mark per text node
    assert saved(root, "article.html")[0]["section"] == "Methods"


def test_repeated_text_anchors_to_the_chosen_occurrence(site, page):
    url, _ = site
    open_doc(page, url + "article.html")
    comment(page, "The same phrase appears twice.", "second one", el="p2", nth=1)
    page.reload()
    open_doc(page, url + "article.html")
    offset = page.evaluate("document.querySelector('#p2 mark.__rv').previousSibling.data.length")
    assert offset == len("The same phrase appears twice. ")


def test_click_highlight_to_edit_and_delete(site, page):
    url, root = site
    open_doc(page, url + "article.html")
    comment(page, "on held-out data", "first")
    page.locator("mark.__rv").first.click()
    assert ui(page, "textarea").input_value() == "first"
    ui(page, "textarea").fill("edited")
    mac = page.evaluate("navigator.platform.startsWith('Mac')")
    ui(page, "textarea").press("Meta+Enter" if mac else "Control+Enter")
    page.wait_for_timeout(300)
    assert saved(root, "article.html")[0]["comment"] == "edited"

    page.on("dialog", lambda d: d.accept())
    page.locator("mark.__rv").first.click()
    ui(page, ".del").click()
    page.wait_for_timeout(300)
    assert marks(page) == []
    assert not (root / "article.html.notes.json").exists()


def test_escape_cancels_a_new_note(site, page):
    url, root = site
    open_doc(page, url + "article.html")
    page.evaluate(SELECT, ["p3", "held-out", 0])
    ui(page, "#add").click()
    ui(page, "textarea").press("Escape")
    assert marks(page) == []
    assert not (root / "article.html.notes.json").exists()


def test_general_note(site, page):
    url, root = site
    open_doc(page, url + "article.html")
    ui(page, "#toggle").click()
    ui(page, ".general").click()
    ui(page, "textarea").fill("Overall: needs a summary up top.")
    ui(page, ".save").click()
    page.wait_for_timeout(300)
    [n] = saved(root, "article.html")
    assert n["quote"] is None and n["anchor"] is None
    assert n["comment"] == "Overall: needs a summary up top."


@pytest.mark.parametrize("secure", [True, False], ids=["clipboard-api", "execcommand-fallback"])
def test_copy_path_and_json(site, browser, secure):
    url, root = site
    ctx = browser.new_context(permissions=["clipboard-read", "clipboard-write"])
    page = ctx.new_page()
    if not secure:  # what plain http on a LAN address looks like
        page.add_init_script("Object.defineProperty(window, 'isSecureContext', { get: () => false })")
    try:
        open_doc(page, url + "article.html")
        page.evaluate(SELECT, ["p3", "held-out", 0])
        ui(page, "#add").click()
        ui(page, "textarea").fill("source?")
        ui(page, ".save").click()
        page.wait_for_timeout(300)
        ui(page, "#toggle").click()
        clip = "() => navigator.clipboard.readText()"

        ui(page, ".copy-path").click()
        page.wait_for_timeout(100)
        assert page.evaluate(clip) == str(root / "article.html.notes.json")
        assert ui(page, ".copy-path").text_content() == "Copied ✓"

        ui(page, ".copy-json").click()
        page.wait_for_timeout(100)
        assert json.loads(page.evaluate(clip)) == json.loads((root / "article.html.notes.json").read_text("utf-8"))
    finally:
        ctx.close()


def test_typing_does_not_trigger_page_shortcuts(site, page):
    url, _ = site
    open_doc(page, url + "article.html")
    page.evaluate(SELECT, ["p3", "held-out", 0])
    ui(page, "#add").click()
    ui(page, "textarea").type("abc")
    assert page.evaluate("window.pageKeys") == 0


def test_svg_text_is_never_wrapped(site, page):
    url, _ = site
    open_doc(page, url + "article.html")
    assert page.evaluate(SELECT, [None, "svg label", 0]) is True
    assert ui(page, "#add").is_hidden()


def test_edited_document_shows_not_found(site, page):
    url, root = site
    open_doc(page, url + "article.html")
    comment(page, "across the corpus", "which corpus?")
    edited = ARTICLE.replace("across the corpus", "on the full set")
    (root / "article.html").write_text(edited, encoding="utf-8", newline="\n")
    page.reload()
    open_doc(page, url + "article.html")
    assert marks(page) == []
    ui(page, "#toggle").click()
    assert ui(page, ".badge").text_content() == "not found"


def test_markdown_document(site, page):
    url, root = site
    open_doc(page, url + "readme.md")
    comment(page, "Install it with uv", "and pipx?")
    [n] = saved(root, "readme.md")
    assert n["section"] == "Readme"
    assert n["quote"] == "Install it with uv"


def test_folder_link_returns_to_listing(site, page):
    url, _ = site
    open_doc(page, url + "readme.md")
    ui(page, "#toggle").click()
    ui(page, ".folder").click()
    page.wait_for_url(url)
    assert "readme.md" in page.content()
