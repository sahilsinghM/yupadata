#!/usr/bin/env python3
"""Learning log + spaced repetition over yupa articles (and later Notion/OneNote/Upsurge exports).

Library: <root>/library/**/article.md (synced from the laptop). State: <root>/learn.db (SQLite).

  learn.py ingest                 add new articles; cards from each quiz (Q -> answer) and key takeaways
  learn.py slot <1|2|3>           today's themed plan: ONE message (11:00 IST) with all lessons of the theme,
                                  slot 1 adds yesterday's check-in + streak, slots 1 and 3 add a due review
  learn.py homework [note]        record that today's applied task was done (accountability)
  learn.py streak                 current streak of days with any quiz answer or homework
  learn.py today                  (old single daily message) newest unsent lesson + 1 due review
  learn.py pending                what the last message asked (so a reply can be graded in any session)
  learn.py answer <card>          the answer to a card
  learn.py grade <card> <again|hard|good|easy>   SM-2 update after the user answers
  learn.py history [n]            what has been studied, newest first
  learn.py search <words>         grep across every article
"""
import datetime as dt, json, os, re, sqlite3, sys
from pathlib import Path

ROOT = Path(os.environ.get("LEARN_ROOT", Path(__file__).resolve().parent))
for _l in ((ROOT / ".env").read_text().splitlines() if (ROOT / ".env").exists() else []):   # personal values live in .env, not git
    _k, _s, _v = _l.partition("=")
    if _s and not _k.startswith("#"):
        os.environ.setdefault(_k.strip(), _v.strip().strip("'\""))
LIB, DB = ROOT / "library", ROOT / "learn.db"
GRADES = {"again": 1, "hard": 3, "good": 4, "easy": 5}


def db():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    con.executescript("""
    create table if not exists items(id integer primary key, path text unique, source text, title text,
        tldr text, added_at text, sent_at text);
    create table if not exists cards(id integer primary key, item_id int, kind text, front text, back text,
        ease real default 2.5, interval int default 0, reps int default 0, lapses int default 0,
        due text, last_grade int, unique(item_id, kind, front));
    create table if not exists state(k text primary key, v text);
    create table if not exists plan(day text, slot int, item_id int, theme text, primary key(day, slot));
    create table if not exists activity(day text, kind text, ref text, at text);
    """)
    return con


def url_of(path):
    """Article link on $NOTES_DOMAIN (slugs.json is written by notes_site.py), else the library path."""
    slugs = json.loads((ROOT / "slugs.json").read_text()) if (ROOT / "slugs.json").exists() else {}
    return f"https://{os.environ['NOTES_DOMAIN']}" + slugs[path] if path in slugs else path


def today():
    return dt.date.today().isoformat()


def parse_article(text):
    """-> title, tldr bullets, quiz [(q, a)], takeaways [str]. Tolerant of small format drift between articles."""
    title = next((l[2:].strip() for l in text.splitlines() if l.startswith("# ")), "Untitled")
    def section(name):
        m = re.search(rf"^(?:\*\*{name}\*\*|#+ {name})\s*$(.*?)(?=^#+ |\Z)", text, re.M | re.S | re.I)
        return m.group(1) if m else ""
    bullets = lambda s: [re.sub(r"^\s*(?:[-*]|\d+\.)\s+", "", l).strip() for l in s.splitlines()
                         if re.match(r"^\s*(?:[-*]|\d+\.)\s+\S", l)]
    tldr = bullets(section("TL;DR"))
    takeaways = bullets(section("Key takeaways"))
    quiz = []
    for m in re.finditer(r"^\*\*\d+\.\s*(.+?)\*\*(.*?)<details><summary>Answer</summary>(.*?)</details>",
                         section("Quiz"), re.M | re.S):
        q = (m.group(1) + " " + m.group(2)).strip()
        a = re.sub(r"<[^>]+>", "", m.group(3)).strip()
        quiz.append((re.sub(r"\s+", " ", q), re.sub(r"\s+", " ", a)))
    # drift seen in headless runs: the question itself inside <summary>
    for m in re.finditer(r"<details><summary>(?!Answer</summary>)\s*(?:\d+\.\s*)?(.+?)</summary>(.*?)</details>", section("Quiz"), re.S):
        quiz.append(tuple(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", g)).strip() for g in m.groups()))
    return title, tldr, quiz, takeaways


# Sango/YouTube titles -> a day theme. C4 lectures use their course name. First match wins.
THEMES = [
    ("Real estate & property", ["real estate", "property", "housing", "builder", "reit", "sector", "plot", "flat", "rera"]),
    ("Loans, EMIs & debt", ["loan", "emi", "debt", "credit"]),
    ("Trading", ["trading", "trade", "intraday", "volume", "breakout", "stop loss", "risk-reward", "chart"]),
    ("Stock market & investing", ["stock", "share", "market", "nifty", "sensex", "invest", "mutual fund", "sip"]),
    ("Money & personal finance", ["financ", "money", "wealth", "tax", "insurance", "budget", "net worth", "net-worth",
                                  "retire", "salary", "gold", "silver", "crypto"]),
    ("Career & work", ["career", "job", "ctc", "talent", "work", "business", "startup"]),
    ("Relationships & family", ["marriage", "relationship", "women", "parent", "child", "family", "love"]),
    ("Health & mind", ["health", "disease", "confident", "stress", "mind", "habit"]),
    ("Tech & coding", ["python", "code", "coding", "programming", "software", "ai ", "machine learning", "data"]),
    ("Astrology & spirituality", ["astro", "kundli", "planet", "saturn", "shani", "rahu", "karma", "spiritual", "numerolog"]),
]


def theme_of(item):
    parts = item["path"].split("/")
    if parts[0] == "c4" and len(parts) > 1:
        return parts[1].replace("-", " ").title()
    t = item["title"].lower()
    hit = next((name for name, kws in THEMES if any(k in t for k in kws)), None)
    if hit:
        return hit
    body = " ".join(json.loads(item["tldr"] or "[]")).lower()   # title too vague -> let the TL;DR decide
    return next((name for name, kws in THEMES if any(k in body for k in kws)), "Life lessons")


def log_activity(con, kind, ref=""):
    con.execute("insert into activity values(?,?,?,?)", (today(), kind, ref, dt.datetime.now().isoformat(timespec="minutes")))


def streak(con, on=None):
    """Consecutive days with any quiz answer or homework, counting back from today (or yesterday if today is empty)."""
    days = {r[0] for r in con.execute("select distinct day from activity")}
    d = dt.date.fromisoformat(on or today())
    if d.isoformat() not in days:
        d -= dt.timedelta(days=1)
    n = 0
    while d.isoformat() in days:
        n, d = n + 1, d - dt.timedelta(days=1)
    return n


def make_plan(con):
    """Today's one lesson: the NEWEST unsent one (fresh material first; older backlog later)."""
    unsent = con.execute("select * from items where sent_at is null order by added_at desc, id desc").fetchall()
    if not unsent:
        return
    theme = theme_of(unsent[0])
    picks = sorted([i for i in unsent if theme_of(i) == theme][:1], key=lambda i: i["id"])   # within a theme: lecture order
    for slot in (1, 2, 3):
        item = picks[slot - 1] if slot <= len(picks) else None
        con.execute("insert or ignore into plan values(?,?,?,?)", (today(), slot, item["id"] if item else None, theme))
    con.commit()


def due_review(con, exclude_items):
    q = ",".join("?" * len(exclude_items)) or "-1"
    return con.execute(f"""select c.*, i.title, i.path from cards c join items i on i.id=c.item_id
                          where c.due<=? and c.item_id not in ({q}) and i.sent_at is not null
                          order by c.due, c.lapses desc, random() limit 1""", (today(), *exclude_items)).fetchone()


def checkin(con):
    """Yesterday's accountability: quizzes answered, homework done, streak."""
    y = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    asked = con.execute("select count(*) from plan where day=? and item_id is not null", (y,)).fetchone()[0]
    if not asked:
        return []
    answered = con.execute("select count(*) from activity where day=? and kind='quiz'", (y,)).fetchone()[0]
    hw = con.execute("select count(*) from activity where day=? and kind='homework'", (y,)).fetchone()[0]
    s = streak(con)
    line = f"✅ Yesterday: {answered} quiz answer(s), homework {'done' if hw else 'NOT done'} · streak {s} day(s)"
    if not answered and not hw:
        line += " — you skipped yesterday. Answer one question from it today to keep the chain."
    return [line, ""]


def cmd_slot(con, slot):
    """ONE message a day: every lesson of today's theme, check-in, a review and the evening question. Slots 2/3 are retired."""
    if slot != 1:
        return print(f"ALREADY SENT slot {slot} today")   # old afternoon/evening jobs, if still scheduled
    ingest_quiet(con)
    key = f"slot_sent:{today()}:1"
    if con.execute("select 1 from state where k=?", (key,)).fetchone():
        return print("ALREADY SENT slot 1 today")
    con.execute("insert into state values(?, '1')", (key,))
    if not con.execute("select 1 from plan where day=?", (today(),)).fetchone():
        make_plan(con)
    rows = con.execute("select * from plan where day=? order by slot", (today(),)).fetchall()
    if not rows:
        return print("Nothing new to learn today, and no plan could be made. 🎉")
    out = [f"🎯 *Today's theme: {rows[0]['theme']}*", ""] + checkin(con)
    today_items = [r["item_id"] for r in rows if r["item_id"]]
    pending = []
    for r in rows:
        lesson = con.execute("select * from items where id=?", (r["item_id"],)).fetchone() if r["item_id"] else None
        if not lesson:
            continue
        out += [f"📘 *{lesson['title']}*"] + [f"• {b}" for b in json.loads(lesson["tldr"])[:2]]
        qs = con.execute("""select * from cards where item_id=? and kind='quiz' and lower(front) not like '%frame%'
                            order by id limit 1""", (lesson["id"],)).fetchall()
        out += [f"Q. {c['front']}  [card {c['id']}]" for c in qs]
        pending += [c["id"] for c in qs]
        out += [f"🔗 Read: {url_of(lesson['path'])}", ""]
        con.execute("update items set sent_at=? where id=?", (today(), lesson["id"]))
    review = due_review(con, today_items)
    if review:
        out += [f"🔁 *Remember this* (from _{review['title']}_ · {url_of(review['path'])}):"]
        if review["kind"] == "quiz":
            out.append(f"{review['front']}  [card {review['id']}]")
            pending.append(review["id"])
        else:
            out.append(review["front"])
            con.execute("update cards set ease=?, interval=?, reps=?, lapses=?, due=?, last_grade=4 where id=?",
                        (*sm2(review, 4), review["id"]))
        out.append("")
    out += ["📝 Reply with quiz answers any time today.",
            "🌙 *Check-in:* did you do today's applied task? Reply with what you did."]
    con.execute("insert or replace into state values('pending', ?)", (json.dumps(pending),))
    con.commit()
    print("\n".join(out))


def ingest(con):
    new = 0
    for p in sorted(LIB.glob("**/article.md")):
        rel = str(p.relative_to(LIB))
        if con.execute("select 1 from items where path=?", (rel,)).fetchone():
            continue
        title, tldr, quiz, takeaways = parse_article(p.read_text())
        cur = con.execute("insert into items(path, source, title, tldr, added_at) values(?,?,?,?,?)",
                          (rel, rel.split("/")[0], title, json.dumps(tldr), today()))
        for q, a in quiz:
            con.execute("insert or ignore into cards(item_id, kind, front, back, due) values(?,?,?,?,?)",
                        (cur.lastrowid, "quiz", q, a, today()))
        for t in takeaways:
            con.execute("insert or ignore into cards(item_id, kind, front, back, due) values(?,?,?,?,?)",
                        (cur.lastrowid, "takeaway", t, "", today()))
        new += 1
    con.commit()
    print(f"ingested {new} new article(s); {con.execute('select count(*) from items').fetchone()[0]} total")


def sm2(card, grade, on=None):
    """SM-2: grade 1..5 -> (ease, interval_days, reps, lapses). Failed recall resets the interval to 1 day."""
    ease, interval, reps, lapses = card["ease"], card["interval"], card["reps"], card["lapses"]
    if grade < 3:
        reps, interval, lapses = 0, 1, lapses + 1
    else:
        reps += 1
        interval = 1 if reps == 1 else 6 if reps == 2 else round(interval * ease)
    ease = max(1.3, ease + 0.1 - (5 - grade) * (0.08 + (5 - grade) * 0.02))
    due = (dt.date.fromisoformat(on or today()) + dt.timedelta(days=interval)).isoformat()
    return ease, interval, reps, lapses, due


def cmd_today(con):
    ingest_quiet(con)
    lesson = con.execute("select * from items where sent_at is null order by added_at, id limit 1").fetchone()
    out, pending = [], []
    if lesson:
        out += [f"📘 *Today's lesson:* {lesson['title']}", ""]
        out += [f"• {b}" for b in json.loads(lesson["tldr"])[:4]]
        # questions pointing at a screenshot ("frame 0088") make no sense on a phone
        qs = con.execute("""select * from cards where item_id=? and kind='quiz' and lower(front) not like '%frame%'
                            order by id limit 3""", (lesson["id"],)).fetchall()
        if qs:
            out += ["", "📝 *Homework quiz* (reply with your answers):"]
            out += [f"Q{i}. {c['front']}  [card {c['id']}]" for i, c in enumerate(qs, 1)]
            pending += [c["id"] for c in qs]
        out += ["", f"_Full notes: {lesson['path']}_"]
        con.execute("update items set sent_at=? where id=?", (today(), lesson["id"]))
    exclude = lesson["id"] if lesson else -1
    review = con.execute("""select c.*, i.title from cards c join items i on i.id=c.item_id
                            where c.due<=? and c.item_id!=? and i.sent_at is not null
                            order by c.due, c.lapses desc, random() limit 1""", (today(), exclude)).fetchone()
    if review:
        out += ["", f"🔁 *Remember this* (from _{review['title']}_):"]
        if review["kind"] == "quiz":
            out.append(f"{review['front']}  [card {review['id']}]")
            pending.append(review["id"])
        else:
            out.append(review["front"])
            # a takeaway is just re-read: schedule it forward as if recalled "good"
            con.execute("update cards set ease=?, interval=?, reps=?, lapses=?, due=?, last_grade=4 where id=?",
                        (*sm2(review, 4), review["id"]))
    if not out:
        out = ["Nothing new today, and no reviews due. 🎉"]
    con.execute("insert or replace into state values('pending', ?)", (json.dumps(pending),))
    con.commit()
    print("\n".join(out))


def ingest_quiet(con):
    import contextlib, io
    with contextlib.redirect_stdout(io.StringIO()):
        ingest(con)


def main(argv):
    con = db()
    cmd, args = (argv[1] if len(argv) > 1 else "today"), argv[2:]
    if cmd == "ingest":
        ingest(con)
    elif cmd == "today":
        cmd_today(con)
    elif cmd == "slot":
        cmd_slot(con, int(args[0]))
    elif cmd == "homework":
        log_activity(con, "homework", " ".join(args))
        con.commit()
        print(f"homework logged for {today()} · streak {streak(con)} day(s)")
    elif cmd == "streak":
        print(f"streak: {streak(con)} day(s)")
    elif cmd == "pending":
        row = con.execute("select v from state where k='pending'").fetchone()
        for cid in json.loads(row["v"]) if row else []:
            c = con.execute("select id, front, back from cards where id=?", (cid,)).fetchone()
            print(f"[card {c['id']}] Q: {c['front']}\n  A: {c['back']}")
    elif cmd == "answer":
        c = con.execute("select front, back from cards where id=?", (int(args[0]),)).fetchone()
        print(f"Q: {c['front']}\nA: {c['back']}")
    elif cmd == "grade":
        cid, grade = int(args[0]), GRADES[args[1]]
        c = con.execute("select * from cards where id=?", (cid,)).fetchone()
        ease, interval, reps, lapses, due = sm2(c, grade)
        con.execute("update cards set ease=?, interval=?, reps=?, lapses=?, due=?, last_grade=? where id=?",
                    (ease, interval, reps, lapses, due, grade, cid))
        log_activity(con, "quiz", str(cid))
        con.commit()
        print(f"card {cid}: next review {due} (in {interval} day(s))")
    elif cmd == "history":
        n = int(args[0]) if args else 30
        for r in con.execute("select title, source, sent_at, added_at from items order by coalesce(sent_at, added_at) desc limit ?", (n,)):
            print(f"{r['sent_at'] or 'queued':10}  [{r['source']}] {r['title']}")
    elif cmd == "search":
        words = [w.lower() for w in args]
        for p in sorted(LIB.glob("**/article.md")):
            for line in p.read_text().splitlines():
                if all(w in line.lower() for w in words):
                    print(f"{p.relative_to(LIB)}: {line.strip()[:200]}")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main(sys.argv)
