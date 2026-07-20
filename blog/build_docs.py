"""Render blog markdown files to self-contained docs/*.html pages.

Matches the styling of the GitHub Pages site and adds Mermaid.js so ```mermaid
fenced blocks render as diagrams. All pages share a brand nav ("The Agentic Studio").
Run: uv run --with markdown python blog/build_docs.py
"""
from __future__ import annotations

import pathlib
import re

import markdown

ROOT = pathlib.Path(__file__).resolve().parent.parent

# slug -> (source markdown, <title>, nav label). Order defines the nav order.
PAGES = {
    "agentic-studio-series": ("blog/agentic-studio-series.md",
                              "The Agentic Studio", "Series"),
    "part-1-thesis": ("blog/part-1-thesis.md",
                      "The Studio Is a Distributed System — The Agentic Studio",
                      "Part 1 · Thesis"),
    "pre-production-barrier": ("blog/pre-production-barrier.md",
                               "Barrier, Fan-out, Join — The Agentic Studio",
                               "Part 2 · Architecture"),
    "part-3-moat": ("blog/part-3-moat.md",
                    "Consistency Is the Product — The Agentic Studio",
                    "Part 3 · Moat"),
    "index": ("blog/mcp-and-skills.md",
              "MCP and Skills — The Agentic Studio", "Foundations · MCP & Skills"),
}

STYLE = """<!doctype html><meta charset=utf-8>
<title>{title}</title><style>
body{{max-width:740px;margin:40px auto;font:17px/1.6 -apple-system,Segoe UI,Roboto,Helvetica,Arial;color:#222;padding:0 16px}}
h1{{font-size:2em;line-height:1.2}} h2{{margin-top:1.6em;border-bottom:1px solid #eee;padding-bottom:.2em}}
h3{{margin-top:1.3em}} hr{{border:none;border-top:2px solid #eee;margin:2.5em 0}}
code{{background:#f4f4f4;padding:2px 5px;border-radius:4px;font-size:.9em}}
pre{{background:#f6f8fa;padding:14px;border-radius:8px;overflow:auto}} pre code{{background:none;padding:0}}
pre.mermaid{{background:#fff;text-align:center}}
table{{border-collapse:collapse;width:100%;margin:1em 0}} th,td{{border:1px solid #ddd;padding:8px 10px;text-align:left;font-size:.92em}}
th{{background:#fafafa}} blockquote{{border-left:4px solid #ddd;margin:1em 0;padding:.2em 1em;color:#555}} img{{max-width:100%}}
nav.posts{{font-size:.9em;color:#666;margin-bottom:1.5em}} nav.posts a{{color:#06c;text-decoration:none}}</style>
"""

MERMAID = ('<script type="module">'
           'import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";'
           'mermaid.initialize({startOnLoad:true,theme:"neutral"});</script>\n')


def nav(active: str) -> str:
    items = []
    for slug, (_src, _title, label) in PAGES.items():
        if slug == active:
            items.append(f"<strong>{label}</strong>")
        else:
            items.append(f'<a href="{slug}.html">{label}</a>')
    return '<nav class="posts">The Agentic Studio: ' + " &middot; ".join(items) + "</nav>\n"


def render(slug: str) -> None:
    src, title, _label = PAGES[slug]
    text = (ROOT / src).read_text()
    md = markdown.Markdown(extensions=["tables", "fenced_code", "sane_lists"])
    html = md.convert(text)

    def _mermaid(m: re.Match) -> str:
        # Markdown HTML-escapes code blocks (< > & "). Mermaid needs the RAW diagram text, so
        # un-escape it. Then drop <br/> line-breaks: a real <br> inside <pre class="mermaid"> is
        # parsed by the browser as a DOM node, splitting the diagram source and breaking parsing —
        # labels render fine single-line.
        import html as _html
        body = _html.unescape(m.group(1))
        body = re.sub(r"\s*<br\s*/?>\s*", " ", body)
        return f'<pre class="mermaid">\n{body}\n</pre>'

    n_mmd = len(re.findall(r'<pre><code class="language-mermaid">', html))
    html = re.sub(r'<pre><code class="language-mermaid">(.*?)</code></pre>',
                  _mermaid, html, flags=re.S)
    out = ROOT / "docs" / f"{slug}.html"
    tail = ("\n" + MERMAID) if n_mmd else "\n"
    out.write_text(STYLE.format(title=title) + nav(slug) + html + tail)
    print(f"wrote docs/{slug}.html  ({n_mmd} mermaid diagrams)")


if __name__ == "__main__":
    for slug in PAGES:
        render(slug)
