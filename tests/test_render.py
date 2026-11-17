from __future__ import annotations

import pytest

from margin_notes.render import MATHJAX_URL, MERMAID_URL, pygments_css, render_markdown


def body(md: str) -> str:
    page = render_markdown(md, "doc.md")
    return page.split('<main class="markdown-body">', 1)[1].split("</main>", 1)[0]


class TestMath:
    def test_inline_and_display_become_mathjax_delimiters(self):
        page = render_markdown("Euler $e^{i\\pi}$.\n\n$$\nx^2\n$$\n", "m.md")
        assert "\\(e^{i\\pi}\\)" in page
        assert "\\[x^2\\]" in page
        assert MATHJAX_URL in page

    def test_math_fence(self):
        assert "\\[a &lt; b\\]" in body("```math\na < b\n```\n")

    def test_tex_is_html_escaped(self):
        out = body("$a<b>c$")
        assert "\\(a&lt;b&gt;c\\)" in out
        assert "<b>" not in out

    def test_underscores_survive_markdown(self):
        # Without the math plugin, _x_ would become <em>.
        assert "\\(a_1 + b_2\\)" in body("$a_1 + b_2$")

    def test_currency_is_not_math(self):
        page = render_markdown("Costs $5 and $10.\n", "p.md")
        assert MATHJAX_URL not in page
        assert "Costs $5 and $10." in page

    def test_mathjax_only_loads_when_needed(self):
        assert MATHJAX_URL not in render_markdown("# Plain\n\nNo math here.\n", "p.md")


class TestCode:
    def test_known_language_is_highlighted(self):
        out = body("```python\ndef f(): pass\n```\n")
        assert '<span class="k">def</span>' in out
        assert 'class="language-python"' in out

    def test_unknown_language_is_escaped_plain(self):
        out = body("```nosuchlang\n<tag>\n```\n")
        assert "&lt;tag&gt;" in out
        assert "<tag>" not in out

    def test_no_language(self):
        assert "<pre><code>x = 1\n</code></pre>" in body("```\nx = 1\n```\n")

    def test_mermaid(self):
        page = render_markdown("```mermaid\ngraph TD; A-->B\n```\n", "d.md")
        assert '<pre class="mermaid">graph TD; A--&gt;B\n</pre>' in page
        assert MERMAID_URL in page

    def test_mermaid_only_loads_when_needed(self):
        assert MERMAID_URL not in render_markdown("```python\nx\n```\n", "d.md")


class TestGfm:
    def test_table(self):
        assert "<table>" in body("| a | b |\n|---|---|\n| 1 | 2 |\n")

    def test_task_list(self):
        out = body("- [x] done\n- [ ] todo\n")
        assert "task-list-item" in out
        assert 'checked="checked"' in out

    def test_strikethrough_and_autolink(self):
        out = body("~~gone~~ see https://example.com\n")
        assert "<s>gone</s>" in out
        assert '<a href="https://example.com">' in out

    def test_footnote(self):
        out = body("Claim.[^1]\n\n[^1]: Source.\n")
        assert 'class="footnotes"' in out

    def test_definition_list(self):
        assert "<dl>" in body("Term\n: Definition\n")

    def test_heading_ids(self):
        out = body("# Hello World\n\n### Deep Dive\n")
        assert 'id="hello-world"' in out
        assert 'id="deep-dive"' in out

    def test_relative_image_untouched(self):
        assert '<img src="img/pic.png" alt="diagram"' in body("![diagram](img/pic.png)\n")

    def test_raw_html_allowed(self):
        assert "<details><summary>More</summary>" in body("<details><summary>More</summary>\n\nHidden\n</details>\n")


class TestAlerts:
    @pytest.mark.parametrize("kind", ["NOTE", "TIP", "IMPORTANT", "WARNING", "CAUTION"])
    def test_each_kind(self, kind):
        out = body(f"> [!{kind}]\n> Be careful.\n")
        assert f'class="alert alert-{kind.lower()}"' in out
        assert f'<p class="alert-title">{kind.title()}</p>' in out
        assert "[!" not in out
        assert "Be careful." in out

    def test_plain_blockquote_untouched(self):
        assert "<blockquote>\n<p>Just a quote.</p>" in body("> Just a quote.\n")


class TestTitle:
    def test_front_matter_title_wins_and_is_hidden(self):
        page = render_markdown("---\ntitle: 'From YAML'\n---\n# From H1\n", "f.md")
        assert "<title>From YAML</title>" in page
        assert "title: " not in body("---\ntitle: x\n---\n# H\n")

    def test_first_h1(self):
        assert "<title>From H1</title>" in render_markdown("Intro\n\n# From H1\n\n# Second\n", "f.md")

    def test_falls_back_to_filename(self):
        assert "<title>notes.md</title>" in render_markdown("## Only h2\n", "notes.md")

    def test_title_is_escaped(self):
        assert "<title>A &lt;b&gt; &amp; C</title>" in render_markdown("# A <b> & C\n", "f.md")


def test_page_shell():
    page = render_markdown("# Hi\n", "f.md")
    assert page.startswith("<!doctype html>")
    assert '<meta name="viewport"' in page
    assert "/__review/static/page.css" in page
    assert page.rstrip().endswith("</html>")
    # The overlay comes last so it can wait for math and diagrams.
    assert page.index("window.__reviewWait = []") < page.index("/__review/static/review.js")


def test_pygments_css_has_light_and_dark_scoped_rules():
    css = pygments_css()
    assert ".markdown-body pre .k " in css
    assert "@media (prefers-color-scheme: dark)" in css
    assert all(line.startswith((".markdown-body pre .", "@media", "}")) for line in css.splitlines() if line)
