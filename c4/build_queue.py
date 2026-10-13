#!/usr/bin/env python3
"""all_rows.csv (every sheet row) -> queue.csv: one section per course, ordered HR -> Ops -> Finance -> Tech -> Other.

Re-running keeps the status of rows already in queue.csv. Edit CATEGORY or reorder queue.csv by hand to change the plan.
"""
import csv, os, re, sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE.parent))
import env; env.load(HERE.parent)
CHANNEL = os.environ.get("SANGO_CHANNEL", "YouTube channel")   # from .env
ORDER = ["sango-money", "sango-other", "sango-public", "hr", "ops", "finance", "tech", "other"]
SANGO_MONEY = ["stock", "share market", "market trend", "market outlook", "trading", "nifty", "sensex", "invest", "financ", "money", "loan", "wealth", "tax",
               "insurance", "mutual fund", "real estate", "reit", "net-worth", "net worth", "bankrupt", "company",
               "portfolio", "sip", "gold", "silver", "crypto", "budget", "retire", "bond", "emi", "salary", "rich",
               "property", "housing", "builder", "sector", "plot", "flat", "rera", "cash flow", "payment plan"]
# ponytail: keyword match on course name; misfiled course -> add its name here
CATEGORY = [
    ("hr", ["strategic hrm", "managing self and others", "strategic leadership", "peak performance",
            "leading technology teams"]),
    ("ops", ["operations management", "supply chain"]),
    ("finance", ["financ", "accounting", "derivatives", "venture capital", "negotiations and deal", "technical analysis",
                 "risk management", "m&a", "investment", "valuation", "defi", "blockchain"]),
    ("tech", ["python", "r programming", "machine learning", "learning models", "big data", "language processing",
              "chatbot", "data query", "visualisation", "no code", "web development", "mvp", "prototyping",
              "product", "gaming", "gamification", "econometrics"]),
]


def category(course):
    c = course.lower()
    return next((cat for cat, kws in CATEGORY if any(k in c for k in kws)), "other")


def base_name(course):
    """'Managerial Accounting Section B' / '...Batch 2' -> 'Managerial Accounting' (sections repeat the same class)."""
    return re.sub(r"[\s-]*(section|batch|batct)\s*\w*\s*$|\s+[A-D]$", "", course.strip(), flags=re.I).strip(" -")


def session_no(name):
    m = re.search(r"session\s*-?\s*(\d+)", name, re.I)
    return int(m.group(1)) if m else None


def main():
    rows = [r for r in csv.DictReader(open(HERE / "all_rows.csv")) if r["kind"] == "file/d"]
    # keep the section with the most recordings for each (term, course)
    groups = {}
    for r in rows:
        groups.setdefault((r["term"], base_name(r["course"])), {}).setdefault(r["course"], []).append(r)
    picked, alts = [], {}
    for secs in groups.values():
        best = max(secs.values(), key=len)
        picked.append(best)
        # same session in the other sections = fallback if the chosen section's file is locked
        for r in best:
            alts[r["id"]] = [o["id"] for sec in secs.values() if sec is not best for o in sec
                             if session_no(o["session"]) is not None and session_no(o["session"]) == session_no(r["session"])]

    old = {r["id"]: r for r in csv.DictReader(open(HERE / "queue.csv"))} if (HERE / "queue.csv").exists() else {}
    queue = []
    for sec in picked:
        for n, r in enumerate(sec, 1):
            queue.append({"category": category(r["course"]), "term": r["term"], "course": base_name(r["course"]),
                          "n": n, "session": r["session"], "master": r["master"], "id": r["id"], "alt_ids": " ".join(alts.get(r["id"], [])),
                          "status": old.get(r["id"], {}).get("status", ""), "done_on": old.get(r["id"], {}).get("done_on", "")})
    # members-only YouTube videos (c4/sango_members.txt: id|availability|secs|yyyymmdd|title)
    if (HERE / "sango_members.txt").exists():
        for line in open(HERE / "sango_members.txt"):
            vid, _, secs, date, title = line.rstrip("\n").split("|", 4)
            cat = "sango-money" if any(re.search(rf"\b{re.escape(k)}", title.lower()) for k in SANGO_MONEY) else "sango-other"
            status = old.get(vid, {}).get("status", "")
            if not status and (HERE.parent / "out" / vid / "article.md").exists():
                status = "done"   # processed by hand before the queue existed
            queue.append({"category": cat, "term": date, "course": CHANNEL, "n": 0, "session": title.strip(),
                          "master": f"{CHANNEL} (members-only)", "id": vid, "alt_ids": "",
                          "status": status, "done_on": old.get(vid, {}).get("done_on", "")})
    # Sango public videos (sango_all.txt minus members-only; no login needed). Shorts (<5 min) skipped.
    if (HERE / "sango_all.txt").exists():
        members = {l.split("|")[0] for l in open(HERE / "sango_members.txt")}
        for line in open(HERE / "sango_all.txt"):
            vid, _, secs, date, title = line.rstrip("\n").split("|", 4)
            if vid in members or int(secs or 0) < 300:
                continue
            queue.append({"category": "sango-public", "term": date, "course": CHANNEL, "n": 0, "session": title.strip(),
                          "master": f"{CHANNEL} (public)", "id": vid, "alt_ids": "",
                          "status": old.get(vid, {}).get("status", ""), "done_on": old.get(vid, {}).get("done_on", "")})
    # C4: Term 1 first; Sango: newest first (term holds yyyymmdd)
    term_no = lambda q: -int(q["term"]) if q["category"].startswith("sango") else int(re.sub(r"\D", "", q["term"]) or 0)
    queue.sort(key=lambda q: (ORDER.index(q["category"]), term_no(q), q["course"], q["n"]))

    with open(HERE / "queue.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(queue[0]))
        w.writeheader()
        w.writerows(queue)
    for cat in ORDER:
        qs = [q for q in queue if q["category"] == cat]
        print(f"{cat:8} {len(qs):4} lectures  {sorted({q['course'] for q in qs})}")
    print("total", len(queue))


if __name__ == "__main__":
    main()
