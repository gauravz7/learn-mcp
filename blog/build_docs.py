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

# slug -> (source markdown, <title>, short nav label, sub-label). Order defines the nav order.
PAGES = {
    "agentic-studio-series": ("blog/agentic-studio-series.md",
                              "The Agentic Studio", "Series", "Overview"),
    "part-1-thesis": ("blog/part-1-thesis.md",
                      "The Studio Is a Distributed System — The Agentic Studio",
                      "Part 1", "Thesis"),
    "pre-production-barrier": ("blog/pre-production-barrier.md",
                               "Barrier, Fan-out, Join — The Agentic Studio",
                               "Part 2", "Architecture"),
    "part-3-moat": ("blog/part-3-moat.md",
                    "Consistency Is the Product — The Agentic Studio",
                    "Part 3", "Moat"),
    "index": ("blog/mcp-and-skills.md",
              "MCP and Skills — The Agentic Studio", "Foundations", "MCP & Skills"),
}

# Absolute site root (GitHub Pages) — required for social-preview images to resolve.
SITE = "https://gauravz7.github.io/movie-studio-agent"

# slug -> (og:image hero under media/, og:description). Controls the LinkedIn/Twitter
# link-preview card so a scraper never falls back to the first inline image (a
# character reference sheet). Heroes are landscape so they don't get letterboxed.
SOCIAL = {
    "agentic-studio-series": ("project-hero.png",
        "An AI film studio built as an agent — a sentence in, a multi-scene short out. "
        "Why the durable value is the orchestration layer, not the render function."),
    "part-1-thesis": ("choice-style.jpg",
        "The disruption in AI video isn't a better render function — it's the coordination "
        "layer around one. Why the studio is a distributed system."),
    "pre-production-barrier": ("seq-callpath.png",
        "Barrier, fan-out, join — the architecture that forces N stochastic outputs to agree, "
        "with the exact Skill + MCP call path and the deterministic gate."),
    "part-3-moat": ("choice-plate-s1.jpg",
        "Anyone can generate a clip; the moat is a thousand clips that agree. The invariants, "
        "the critic loop, and the unit economics of consistency."),
    "index": ("seq-callpath.png",
        "MCP and Skills — the two standards behind an agentic studio. What each is, why you "
        "need both, and the context economics that only show up when you ship."),
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
video{{max-width:100%;border-radius:10px;box-shadow:0 6px 24px rgba(0,0,0,.14);margin:.4em 0}}
.gallery{{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:1.2em 0}}
.gallery figure{{margin:0}} .gallery figcaption{{font-size:.82em;color:#777;margin-top:4px}}
.site-nav{{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;margin:0 0 2em;padding-bottom:12px;border-bottom:1px solid #eee}}
.site-nav .brand{{font-weight:700;color:#111;text-decoration:none;font-size:1.05em;margin-right:auto}}
.navlinks{{display:flex;flex-wrap:wrap;gap:6px}}
.nav-item{{text-decoration:none;color:#06c;padding:5px 12px;border-radius:999px;font-size:.92em;white-space:nowrap;transition:background .12s}}
.nav-item:hover{{background:#eef5ff}}
.nav-item.active{{background:#06c;color:#fff;pointer-events:none}}</style>
"""

MERMAID = ('<script type="module">'
           'import mermaid from "https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs";'
           'mermaid.initialize({startOnLoad:true,theme:"neutral"});</script>\n')

# Open Graph + Twitter Card so LinkedIn/X render a controlled preview card.
SOCIAL_META = (
    '<meta property="og:type" content="article">'
    '<meta property="og:site_name" content="The Agentic Studio">'
    '<meta property="og:title" content="{title}">'
    '<meta property="og:description" content="{desc}">'
    '<meta property="og:image" content="{site}/media/{hero}">'
    '<meta property="og:url" content="{site}/{slug}.html">'
    '<meta name="twitter:card" content="summary_large_image">'
    '<meta name="twitter:title" content="{title}">'
    '<meta name="twitter:description" content="{desc}">'
    '<meta name="twitter:image" content="{site}/media/{hero}">'
    '<meta name="description" content="{desc}">\n')


def nav(active: str) -> str:
    links = []
    for slug, (_src, _title, short, sub) in PAGES.items():
        cls = "nav-item active" if slug == active else "nav-item"
        href = "#" if slug == active else f"{slug}.html"
        links.append(f'<a class="{cls}" href="{href}" title="{sub}">{short}</a>')
    return ('<header class="site-nav">'
            '<a class="brand" href="agentic-studio-series.html">🎬 The Agentic Studio</a>'
            '<nav class="navlinks">' + "".join(links) + "</nav></header>\n")


def render(slug: str) -> None:
    src, title, _short, _sub = PAGES[slug]
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
    hero, desc = SOCIAL[slug]
    meta = SOCIAL_META.format(site=SITE, slug=slug, title=title, desc=desc, hero=hero)
    out.write_text(STYLE.format(title=title) + meta + nav(slug) + html + tail)
    print(f"wrote docs/{slug}.html  (og:image={hero})")


if __name__ == "__main__":
    for slug in PAGES:
        render(slug)
