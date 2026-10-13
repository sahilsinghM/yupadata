#!/usr/bin/env python3
"""Render out/<id>/article.md to article.html next to it (so frames/ resolve) and open it.

Usage: view.py out/<id>
"""
import html, json, subprocess, sys
from pathlib import Path

PAGE = """<!doctype html><meta charset="utf-8"><title>{title}</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root{{--bg:#fbfaf7;--fg:#1d1d1f;--muted:#6b6b70;--line:#e4e2dc;--code:#f1efe9;--accent:#b4541a}}
@media (prefers-color-scheme:dark){{:root{{--bg:#16161a;--fg:#e8e6e1;--muted:#9a978f;--line:#2e2d33;--code:#222127;--accent:#f0a060}}}}
body{{background:var(--bg);color:var(--fg);font:17px/1.65 Charter,"Iowan Old Style",Georgia,serif;margin:0;padding:3rem 1rem}}
main{{max-width:760px;margin:auto}}
h1{{font-size:2.1rem;line-height:1.2}} h2{{margin-top:2.6rem;border-top:1px solid var(--line);padding-top:1.4rem}}
h1,h2,h3,table,blockquote,summary{{font-family:system-ui,sans-serif}}
img{{max-width:100%;border-radius:8px;display:block;margin:1.4rem 0 .3rem}}
img+em,p>em:only-child{{display:block;color:var(--muted);font-size:.9rem;margin-bottom:1.4rem}}
code{{background:var(--code);padding:.1em .35em;border-radius:4px;font-size:.88em}}
pre{{background:var(--code);padding:1rem;border-radius:8px;overflow-x:auto}} pre code{{padding:0}}
table{{border-collapse:collapse;width:100%;font-size:.9rem;display:block;overflow-x:auto}}
th,td{{border:1px solid var(--line);padding:.45rem .6rem;text-align:left;vertical-align:top}}
blockquote{{margin:1rem 0;padding:.6rem 1rem;border-left:3px solid var(--accent);color:var(--muted);font-size:.95rem}}
details{{background:var(--code);border-radius:8px;padding:.5rem .9rem;margin:.4rem 0 1.4rem}} summary{{cursor:pointer;color:var(--accent)}}
a{{color:var(--accent)}}
</style>
<main id="a"></main>
<script src="https://cdnjs.cloudflare.com/ajax/libs/marked/12.0.2/marked.min.js"></script>
<script>document.getElementById('a').innerHTML = marked.parse({md});</script>
"""

if __name__ == "__main__":
    out = Path(sys.argv[1])
    md = (out / "article.md").read_text()
    title = next((l[2:] for l in md.splitlines() if l.startswith("# ")), out.name)
    dest = out / "article.html"
    # ponytail: marked from CDN, needs internet on first view; vendor it if you read offline
    dest.write_text(PAGE.format(title=html.escape(title), md=json.dumps(md).replace("</", "<\\/")))
    subprocess.Popen(["xdg-open", str(dest)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(dest)
