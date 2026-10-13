#!/usr/bin/env python3
"""Pull Notion + OneNote pages into the learning library as lesson articles.

  notes_sync.py                 sync both sources (only new/changed pages), then learn.py ingest
  notes_sync.py notion|onenote  one source
  notes_sync.py onenote-login   one-time Microsoft device-code sign-in (interactive)
  notes_sync.py list            what has been pulled so far

Config: /root/learning/.env
  NOTION_TOKEN=secret_...            optional. Empty = use the claude.ai Notion connector via headless Claude Code
  MS_CLIENT_ID=...                   Azure app (public client, delegated Notes.Read) - see docs
  MS_AUTHORITY=consumers             consumers (personal Microsoft account) | organizations | common
  NOTES_MAX_PER_RUN=10               cap on pages turned into articles per run (Claude usage)
Raw exports: sources/<src>/<id>.md ; articles: library/<src>/<id>/article.md (via headless Claude).
"""
import html.parser, json, os, re, subprocess, sys, time, urllib.request
from pathlib import Path

ROOT = Path(os.environ.get("LEARN_ROOT", Path(__file__).resolve().parent))
SRC, LIB, STATE = ROOT / "sources", ROOT / "library", ROOT / "notes_state.json"
CLAUDE = str(Path.home() / ".local/bin/claude")
MIN_CHARS = 400   # skip near-empty pages (titles, stubs)


def env():
    e = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                e[k.strip()] = v.strip()
    return e


def http(url, token, data=None, method=None, headers=None):
    h = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", **(headers or {})}
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers=h, method=method or ("POST" if body else "GET"))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
                return json.loads(raw) if "json" in r.headers.get("Content-Type", "") else raw.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < 3:
                time.sleep(int(e.headers.get("Retry-After") or 2 ** attempt * 5))
                continue
            raise


# ---------------- Notion ----------------
NOTION = "https://api.notion.com/v1"
NV = {"Notion-Version": "2022-06-28"}


def notion_text(rich):
    return "".join(t.get("plain_text", "") for t in rich or [])


def notion_blocks_md(token, block_id, depth=0):
    """Blocks -> markdown-ish text (headings, lists, todos, quotes, code, toggles, children)."""
    out, cursor = [], None
    while True:
        q = f"?page_size=100" + (f"&start_cursor={cursor}" if cursor else "")
        d = http(f"{NOTION}/blocks/{block_id}/children{q}", token, headers=NV)
        for b in d["results"]:
            t, v = b["type"], b.get(b["type"], {})
            txt = notion_text(v.get("rich_text"))
            pre = "  " * depth
            line = {"heading_1": f"# {txt}", "heading_2": f"## {txt}", "heading_3": f"### {txt}",
                    "bulleted_list_item": f"{pre}- {txt}", "numbered_list_item": f"{pre}1. {txt}",
                    "to_do": f"{pre}- [{'x' if v.get('checked') else ' '}] {txt}", "quote": f"> {txt}",
                    "callout": f"> {txt}", "toggle": f"{pre}- {txt}",
                    "code": f"```\n{txt}\n```", "child_page": f"(sub-page: {v.get('title', '')})"}.get(t, txt)
            if line.strip():
                out.append(line)
            if b.get("has_children") and t not in ("child_page", "child_database"):
                out.append(notion_blocks_md(token, b["id"], depth + 1))
        if not d.get("has_more"):
            return "\n".join(x for x in out if x)
        cursor = d["next_cursor"]


def notion_title(page):
    for p in page.get("properties", {}).values():
        if p.get("type") == "title":
            return notion_text(p["title"]) or "Untitled"
    return "Untitled"


def notion_pages(token):
    """Every page shared with the integration: (id, title, last_edited, url)."""
    cursor = None
    while True:
        body = {"filter": {"property": "object", "value": "page"}, "page_size": 100}
        if cursor:
            body["start_cursor"] = cursor
        d = http(f"{NOTION}/search", token, body, headers=NV)
        for p in d["results"]:
            if not p.get("archived") and not p.get("in_trash"):
                yield p["id"], notion_title(p), p["last_edited_time"], p.get("url", "")
        if not d.get("has_more"):
            return
        cursor = d["next_cursor"]


NOTION_MCP_PROMPT = """You have Notion tools (claude.ai Notion connector). Task: bring the user's Notion notes into their study library.
1. Use notion-search to find pages {since}. Ignore databases themselves, templates, empty pages and pages under
   {max_chars} characters. Pages already processed (skip unless edited after the given time): {known}.
2. For at most {limit} pages (most recently edited first): notion-fetch the page, then write a study article to
   {lib}/<page-id-without-dashes>/article.md using ONLY the page's content, in exactly this format:
{fmt}
3. Finally print ONE line of JSON and nothing after it:
   {{"pages": [{{"id": "<page id>", "title": "<title>", "edited": "<last edited ISO time>", "article": "<path>"}}]}}"""


def pull_notion_mcp(e, state, limit):
    """No API token: let headless Claude Code read Notion through the claude.ai Notion connector."""
    last = state.get("_notion_mcp_last")
    known = [v["title"] for k, v in state.items() if k.startswith("notion:")][:200]
    fmt = ARTICLE_PROMPT.split("Format exactly:")[1].split("Write the article to")[0].replace("{src}", "Notion").replace('"{title}"', "<page title>")
    prompt = NOTION_MCP_PROMPT.format(since=f"edited after {last}" if last else "that hold his notes (any date)",
                                      max_chars=MIN_CHARS, known=json.dumps(known), limit=limit,
                                      lib=LIB / "notion", fmt=fmt)
    started = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    r = subprocess.run([CLAUDE, "-p", prompt, "--model", "sonnet", "--permission-mode", "acceptEdits", "--allowedTools",
                        "mcp__claude_ai_Notion__notion-search", "mcp__claude_ai_Notion__notion-fetch", "Write"],
                       cwd=ROOT, capture_output=True, text=True, timeout=3600)
    line = next((l for l in reversed(r.stdout.strip().splitlines()) if l.strip().startswith("{")), None)
    if not line:
        return print(f"notion (connector): no result; is Notion connected at claude.ai -> Settings -> Connectors? {r.stdout[-300:]}")
    for p in json.loads(line).get("pages", []):
        state[f"notion:{p['id']}"] = {"edited": p.get("edited", ""), "title": p.get("title", ""), "file": "", "article": True}
        print(f"notion (connector): {p.get('title', '')[:70]}")
    state["_notion_mcp_last"] = started


def pull_notion(e, state):
    tok = e.get("NOTION_TOKEN")
    if not tok:
        return pull_notion_mcp(e, state, int(e.get("NOTES_MAX_PER_RUN", 10)))
    for pid, title, edited, url in notion_pages(tok):
        key = f"notion:{pid}"
        if state.get(key, {}).get("edited") == edited:
            continue
        body = notion_blocks_md(tok, pid)
        save_source("notion", pid, title, url, edited, body, state)


# ---------------- OneNote (Microsoft Graph) ----------------
GRAPH = "https://graph.microsoft.com/v1.0"
SCOPES = ["Notes.Read"]


def ms_app(e):
    import msal
    cache = msal.SerializableTokenCache()
    cf = ROOT / ".ms_token_cache.json"
    if cf.exists():
        cache.deserialize(cf.read_text())
    app = msal.PublicClientApplication(e["MS_CLIENT_ID"], token_cache=cache,
                                       authority=f"https://login.microsoftonline.com/{e.get('MS_AUTHORITY', 'consumers')}")
    return app, cache, cf


def ms_token(e):
    app, cache, cf = ms_app(e)
    accts = app.get_accounts()
    res = app.acquire_token_silent(SCOPES, account=accts[0]) if accts else None
    if cache.has_state_changed:
        cf.write_text(cache.serialize()); cf.chmod(0o600)
    if not res or "access_token" not in res:
        raise RuntimeError("OneNote not signed in (or token expired): run `notes_sync.py onenote-login`")
    return res["access_token"]


def onenote_login(e):
    app, cache, cf = ms_app(e)
    flow = app.initiate_device_flow(scopes=SCOPES)
    if "user_code" not in flow:
        sys.exit(f"device flow failed: {flow}")
    print(flow["message"], flush=True)          # "go to https://microsoft.com/devicelogin and enter CODE"
    res = app.acquire_token_by_device_flow(flow)
    cf.write_text(cache.serialize()); cf.chmod(0o600)
    print("signed in as", (res.get("id_token_claims") or {}).get("preferred_username") if "access_token" in res else res)


class _Text(html.parser.HTMLParser):
    """OneNote page HTML -> plain text with simple heading/list markers."""
    def __init__(self):
        super().__init__()
        self.out, self.prefix = [], ""
    def handle_starttag(self, tag, attrs):
        if tag in ("h1", "h2", "h3"):
            self.out.append("\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.out.append("\n- ")
        elif tag in ("p", "br", "div", "tr"):
            self.out.append("\n")
    def handle_data(self, data):
        self.out.append(data)
    def text(self):
        return re.sub(r"\n\s*\n+", "\n\n", "".join(self.out)).strip()


def html_to_text(s):
    p = _Text()
    p.feed(s)
    return p.text()


def pull_onenote(e, state):
    if not e.get("MS_CLIENT_ID"):
        return print("onenote: no MS_CLIENT_ID in .env; skipping")
    tok = ms_token(e)
    url = f"{GRAPH}/me/onenote/pages?$top=100&$select=id,title,lastModifiedDateTime,links&$expand=parentSection($select=displayName)"
    while url:
        d = http(url, tok)
        for p in d["value"]:
            key = f"onenote:{p['id']}"
            if state.get(key, {}).get("edited") == p["lastModifiedDateTime"]:
                continue
            body = html_to_text(http(f"{GRAPH}/me/onenote/pages/{p['id']}/content", tok))
            section = (p.get("parentSection") or {}).get("displayName", "")
            link = ((p.get("links") or {}).get("oneNoteWebUrl") or {}).get("href", "")
            save_source("onenote", p["id"], f"{section} · {p['title']}" if section else p["title"],
                        link, p["lastModifiedDateTime"], body, state)
        url = d.get("@odata.nextLink")


# ---------------- common ----------------
def safe_id(pid):
    return re.sub(r"[^A-Za-z0-9_-]", "", pid)[:80]


def save_source(src, pid, title, url, edited, body, state):
    (SRC / src).mkdir(parents=True, exist_ok=True)
    f = SRC / src / f"{safe_id(pid)}.md"
    f.write_text(f"# {title}\n\nSource: {url}\nLast edited: {edited}\n\n{body}\n")
    state[f"{src}:{pid}"] = {"edited": edited, "title": title, "file": str(f.relative_to(ROOT)), "article": False}
    print(f"{src}: pulled {title[:70]} ({len(body)} chars)")


ARTICLE_PROMPT = """Turn the user's own note below into a study article for their spaced-repetition system.
Use ONLY what the note says (no outside facts; if something is unclear, leave it out). Write in English.
Format exactly:
# <clear title>
Source: {src} note "{title}"

**TL;DR**
- 3-5 bullets

## <sections that organise the note's ideas; explain the why where the note does>

## Key takeaways
1. ...

## Quiz
5 questions testing the note's content, each exactly:
**1. Question?**
a) ... b) ... (only for multiple choice)
<details><summary>Answer</summary>Answer + one-line explanation.</details>

Write the article to {out} and stop.

--- NOTE ---
{body}"""


def make_articles(state, limit):
    todo = [(k, v) for k, v in state.items() if not k.startswith("_") and not v.get("article")]
    for key, v in todo[:limit]:
        src, pid = key.split(":", 1)
        body = (ROOT / v["file"]).read_text()
        if len(body) < MIN_CHARS:
            v["article"] = "skipped-short"
            continue
        out = LIB / src / safe_id(pid) / "article.md"
        out.parent.mkdir(parents=True, exist_ok=True)
        prompt = ARTICLE_PROMPT.format(src=src.title(), title=v["title"], out=out, body=body[:60000])
        r = subprocess.run([CLAUDE, "-p", prompt, "--model", "sonnet", "--permission-mode", "acceptEdits",
                            "--allowedTools", "Write"], cwd=ROOT, capture_output=True, text=True, timeout=900)
        if out.exists():
            v["article"] = True
            print(f"article: {v['title'][:60]}")
        else:
            print(f"article FAILED for {v['title'][:60]}: {(r.stdout or r.stderr)[-200:]}")
    if len(todo) > limit:
        print(f"{len(todo) - limit} page(s) left for the next run (NOTES_MAX_PER_RUN={limit})")


def main(argv):
    e = env()
    cmd = argv[1] if len(argv) > 1 else "all"
    if cmd == "onenote-login":
        return onenote_login(e)
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    if cmd == "list":
        for k, v in sorted(i for i in state.items() if not i[0].startswith("_")):
            print(f"{k.split(':')[0]:8} {str(v.get('article')):14} {v['edited'][:10]}  {v['title'][:80]}")
        return
    try:
        if cmd in ("all", "notion"):
            pull_notion(e, state)
        if cmd in ("all", "onenote"):
            pull_onenote(e, state)
    finally:
        STATE.write_text(json.dumps(state, indent=1))
    make_articles(state, int(e.get("NOTES_MAX_PER_RUN", 10)))
    STATE.write_text(json.dumps(state, indent=1))
    subprocess.run([sys.executable, str(ROOT / "learn.py"), "ingest"], check=False)


if __name__ == "__main__":
    main(sys.argv)
