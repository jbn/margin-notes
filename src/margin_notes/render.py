"""Markdown -> a standalone, styled HTML page (GFM, code highlighting, math, mermaid)."""

from __future__ import annotations

import html
import re
from functools import lru_cache

from markdown_it import MarkdownIt
from mdit_py_plugins.anchors import anchors_plugin
from mdit_py_plugins.deflist import deflist_plugin
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.front_matter import front_matter_plugin
from mdit_py_plugins.tasklists import tasklists_plugin
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_by_name
from pygments.util import ClassNotFound

MATHJAX_URL = "https://cdn.jsdelivr.net/npm/mathjax@3.2.2/es5/tex-mml-chtml.js"
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@11.4.1/dist/mermaid.esm.min.mjs"

ALERTS = {"NOTE": "Note", "TIP": "Tip", "IMPORTANT": "Important", "WARNING": "Warning", "CAUTION": "Caution"}
_ALERT_RE = re.compile(r"<blockquote>\s*<p>\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*(?:<br\s*/?>)?\s*")


def _highlight(code: str, lang: str, _attrs: str) -> str:
    if not lang:
        return ""  # markdown-it escapes it as plain code
    try:
        lexer = get_lexer_by_name(lang)
    except ClassNotFound:
        return ""
    return highlight(code, lexer, HtmlFormatter(nowrap=True))


def _math(content: str, opts: dict) -> str:
    # Emit TeX with MathJax delimiters; MathJax typesets it in the browser.
    tex = html.escape(content)
    return f"\\[{tex}\\]" if opts.get("display_mode") else f"\\({tex}\\)"


@lru_cache(maxsize=1)
def _parser() -> MarkdownIt:
    md = MarkdownIt("gfm-like", {"highlight": _highlight, "typographer": False})
    md.use(front_matter_plugin)
    md.use(footnote_plugin)
    md.use(deflist_plugin)
    md.use(tasklists_plugin)
    md.use(anchors_plugin, min_level=1, max_level=6)
    md.use(dollarmath_plugin, renderer=_math, double_inline=True, allow_digits=False)

    default_fence = md.renderer.rules["fence"]

    def fence(self, tokens, idx, options, env):
        info = tokens[idx].info.strip()
        lang = info.split(maxsplit=1)[0].lower() if info else ""
        if lang == "mermaid":
            return f'<pre class="mermaid">{html.escape(tokens[idx].content)}</pre>\n'
        if lang == "math":
            return f'<div class="math block">\\[{html.escape(tokens[idx].content.strip())}\\]</div>\n'
        return default_fence(tokens, idx, options, env)

    md.add_render_rule("fence", fence)
    return md


@lru_cache(maxsize=1)
def pygments_css() -> str:
    def defs(style: str) -> str:
        lines = HtmlFormatter(style=style).get_style_defs(".markdown-body pre").splitlines()
        # Drop the base rule (background/colour) and unscoped rules; page.css owns those.
        return "\n".join(line for line in lines if line.startswith(".markdown-body pre ."))

    return f"{defs('default')}\n@media (prefers-color-scheme: dark) {{\n{defs('github-dark')}\n}}\n"


def _title(tokens, fallback: str) -> str:
    for i, tok in enumerate(tokens):
        if tok.type == "front_matter":
            m = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", tok.content, re.M)
            if m:
                return m.group(1)
        if tok.type == "heading_open" and tok.tag == "h1" and i + 1 < len(tokens):
            return tokens[i + 1].content
    return fallback


def render_markdown(text: str, name: str) -> str:
    md = _parser()
    tokens = md.parse(text, {})
    body = md.renderer.render(tokens, md.options, {})
    body = _ALERT_RE.sub(
        lambda m: (
            f'<blockquote class="alert alert-{m.group(1).lower()}"><p class="alert-title">{ALERTS[m.group(1)]}</p><p>'
        ),
        body,
    )
    title = html.escape(_title(tokens, name))
    has_math = 'class="math' in body
    has_mermaid = 'class="mermaid"' in body

    head = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        f"<title>{title}</title>",
        '<link rel="stylesheet" href="/__review/static/page.css">',
        f"<style>{pygments_css()}</style>",
        "<script>window.__reviewWait = [];</script>",
    ]
    if has_math:
        head.append(
            """<script>
window.__reviewWait.push(new Promise((done) => {
  window.MathJax = {
    tex: { inlineMath: [["\\\\(", "\\\\)"]], displayMath: [["\\\\[", "\\\\]"]], tags: "ams" },
    options: { ignoreHtmlClass: "tex2jax_ignore", processHtmlClass: "math" },
    startup: { pageReady: () => MathJax.startup.defaultPageReady().then(done, done) },
  };
}));
</script>"""
        )
        head.append(f'<script defer src="{MATHJAX_URL}"></script>')
    tail = []
    if has_mermaid:
        tail.append(
            f"""<script type="module">
import mermaid from "{MERMAID_URL}";
const dark = matchMedia("(prefers-color-scheme: dark)").matches;
mermaid.initialize({{ startOnLoad: false, theme: dark ? "dark" : "default" }});
window.__reviewWait.push(mermaid.run({{ querySelector: "pre.mermaid" }}).catch(console.error));
</script>"""
        )
    tail.append('<script src="/__review/static/review.js" defer></script>')
    return (
        '<!doctype html>\n<html lang="en">\n<head>\n'
        + "\n".join(head)
        + f'\n</head>\n<body class="mn-page">\n<main class="markdown-body">\n{body}</main>\n'
        + "\n".join(tail)
        + "\n</body>\n</html>\n"
    )
