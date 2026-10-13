#!/usr/bin/env python3
"""Build the private notes site ($NOTES_DOMAIN) from the learning library.

  library/sango/<id>/article.md        -> /sango/<title-slug>/
  library/c4/<course>/<nn>/article.md  -> /c4/<course>/<nn>-<session-slug>/
  library/youtube/<id>/article.md      -> /youtube/<title-slug>/
Slugs are stored in <root>/slugs.json and never change once assigned (Telegram links stay valid).
Index pages at /, /sango/, /c4/, /c4/<course>/, /youtube/ with full-text search (search.json).
Run after each ingest (vps/sync.py does): python3 vps/notes_site.py
"""
import html, json, os, re, shutil, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from view import PAGE
import env; env.load(os.environ.get("LEARN_ROOT", "/root/learning"))

ROOT = Path(os.environ.get("LEARN_ROOT", "/root/learning"))
LIB, SLUGS = ROOT / "library", ROOT / "slugs.json"
OUT = Path(os.environ.get("NOTES_OUT", "/var/www/notes"))
BASE = f"https://{os.environ['NOTES_DOMAIN']}"
SECTIONS = {"sango": os.environ.get("SANGO_CHANNEL", "YouTube channel"), "c4": "C4 courses", "youtube": "YouTube"}

SEARCH_JS = """<script>
const m=document.getElementById('a'),orig=m.innerHTML,q=document.createElement('input');let D;
q.type='search';q.placeholder='Search all notes…';
q.style.cssText='width:100%;box-sizing:border-box;font:inherit;padding:.6rem .8rem;border-radius:8px;border:1px solid var(--line);background:var(--code);color:var(--fg)';
m.before(q);
const esc=s=>s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
q.oninput=async()=>{D=D||await(await fetch('/search.json')).json();
 const w=q.value.toLowerCase().split(/\\s+/).filter(Boolean);
 if(!w.length){m.innerHTML=orig;return}
 const hits=D.filter(d=>w.every(x=>d.x.includes(x)));
 m.innerHTML='<h2>'+hits.length+' result(s)</h2><ul>'+hits.map(d=>'<li><a href="'+d.u+'">'+esc(d.t)+'</a></li>').join('')+'</ul>'};
</script>"""


def slugify(s, n=60):
    s = re.sub(r"[^a-z0-9]+", "-", re.sub(r"['’]", "", s.lower())).strip("-")
    return s if len(s) <= n else s[:n].rsplit("-", 1)[0]


def url_for(rel, title):
    """Library path (e.g. c4/strategic-hrm/05/article.md) + title -> site path without the clash suffix."""
    parts = rel.split("/")
    if parts[0] == "c4":
        name = slugify(title.split(":", 1)[1] if ":" in title else title)
        return f"/c4/{parts[1]}/{parts[2]}-{re.sub(r'^session-\d+-', '', name)}/"
    return f"/{parts[0]}/{slugify(title)}/"


def assign(articles, slugs):
    """Give each new article a unique url; existing ones keep theirs. articles: [(rel, title)]."""
    taken = set(slugs.values())
    for rel, title in articles:
        if rel in slugs:
            continue
        base = url = url_for(rel, title)
        n = 2
        while url in taken:
            url, n = f"{base[:-1]}-{n}/", n + 1
        slugs[rel] = url
        taken.add(url)
    return slugs


def page(title, md, search=False):
    return PAGE.format(title=html.escape(title), md=json.dumps(md).replace("</", "<\\/")) + (SEARCH_JS if search else "")


def write(url, text):
    d = OUT / url.strip("/")
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text(text)


def plain(md):
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)|<[^>]+>|[*_#`>|]", " ", md)
    return re.sub(r"\s+", " ", md).lower()


def course_name(slug):
    return slug.replace("-", " ").title().replace("Hrm", "HRM")


def build():
    arts = []
    for p in LIB.glob("**/article.md"):
        md = p.read_text()
        title = next((l[2:].strip() for l in md.splitlines() if l.startswith("# ")), p.parent.name)
        arts.append({"rel": str(p.relative_to(LIB)), "title": title, "md": md, "dir": p.parent, "mtime": p.stat().st_mtime})
    slugs = json.loads(SLUGS.read_text()) if SLUGS.exists() else {}
    assign([(a["rel"], a["title"]) for a in sorted(arts, key=lambda a: a["mtime"])], slugs)
    SLUGS.write_text(json.dumps(slugs, indent=1))

    for a in arts:
        a["url"] = slugs[a["rel"]]
        parts = a["rel"].split("/")
        up = f"/c4/{parts[1]}/" if parts[0] == "c4" else f"/{parts[0]}/"
        up_name = course_name(parts[1]) if parts[0] == "c4" else SECTIONS[parts[0]]
        write(a["url"], page(a["title"], f"[← Notes](/) · [{up_name}]({up})\n\n{a['md']}"))
        if (a["dir"] / "frames").exists():
            shutil.copytree(a["dir"] / "frames", OUT / a["url"].strip("/") / "frames", dirs_exist_ok=True)

    link = lambda a: f"- [{a['title']}]({a['url']})"
    newest = sorted(arts, key=lambda a: -a["mtime"])
    courses = sorted({a["rel"].split("/")[1] for a in arts if a["rel"].startswith("c4/")})
    for sec, name in SECTIONS.items():
        if sec == "c4":
            body = "\n".join(f"- [{course_name(c)}](/c4/{c}/)" for c in courses)
        else:
            body = "\n".join(link(a) for a in newest if a["rel"].startswith(sec + "/"))
        write(f"/{sec}/", page(name, f"[← Notes](/)\n\n# {name}\n\n{body}", search=True))
    for c in courses:
        sess = sorted((a for a in arts if a["rel"].startswith(f"c4/{c}/")), key=lambda a: a["rel"])
        write(f"/c4/{c}/", page(course_name(c), f"[← Notes](/) · [C4 courses](/c4/)\n\n# {course_name(c)}\n\n"
                                 + "\n".join(link(a) for a in sess), search=True))
    count = lambda sec: sum(a["rel"].startswith(sec + "/") for a in arts)
    home = "# Notes\n\n" + "\n".join(f"- [{n}](/{s}/) ({count(s)})" for s, n in SECTIONS.items()) \
        + "\n\n## Latest\n\n" + "\n".join(link(a) for a in newest[:15])
    write("/", page("Notes", home, search=True))
    # ponytail: whole-library search.json, fine to a few hundred articles; switch to pagefind if it gets slow on phone
    (OUT / "search.json").write_text(json.dumps([{"t": a["title"], "u": a["url"], "x": plain(a["md"])} for a in arts]))
    print(f"site: {len(arts)} articles -> {OUT}")


if __name__ == "__main__":
    build()
