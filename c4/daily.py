#!/usr/bin/env python3
"""Process the next C4 lecture from queue.csv: Drive video -> timeline (yupa.py) -> article + quiz (headless Claude).

Run by the yupa-daily systemd timer every hour; starts a lecture at most once every EVERY_HOURS.
Manual run: python3 c4/daily.py [--force] [--only id,id]   (--force ignores the interval and 5-hour guards;
  --only runs just those queued videos now, ignoring the interval but still waiting out a full 5-hour window)
Status per row in queue.csv: "" = todo, done, failed, noaccess (Drive 404 for your account). Clear the cell to retry.
"""
import csv, datetime, fcntl, os, re, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import env; env.load(ROOT)   # personal values come from .env
CHANNEL = os.environ.get("SANGO_CHANNEL", "YouTube channel")
C4 = ROOT / "c4"
QUEUE, STAMP, LOG = C4 / "queue.csv", C4 / "last_run", C4 / "daily.log"
CATEGORIES = ("sango", "hr", "ops", "finance", "tech", "other")  # user 2026-10-11: C4 opened; odd hours prefer C4, even hours Sango
EVERY_HOURS = 1       # normal pace: one lecture per this many hours (1 while finishing Sango)
SLOW_HOURS = 24       # pace once the weekly Claude limit is getting used up
WEEKLY_LIMIT_PCT = 70 # switch to SLOW_HOURS at/above this % of the 7-day limit
PACE = C4 / "pace"    # last pace, so a switch is announced once
FIVE_HOUR_SKIP_PCT = 90  # 5-hour window nearly used up -> skip this slot (retry next hourly check) instead of failing
MODEL = "sonnet"  # ponytail: one knob; "opus" for better articles at ~2x the usage
COOKIE_FILE = ROOT / "cookies.txt"          # present on the VPS (exported from Brave); absent on the laptop
HEADLESS = COOKIE_FILE.exists()
MIN_FREE_GB = 5


def auth_args():
    """yt-dlp writes the jar back after every call (a full disk once truncated it), so use a fresh copy each time."""
    if not HEADLESS:
        return ["--cookies-from-browser", "brave+gnomekeyring"]
    tmp = Path(f"/tmp/yupa-cookies-{os.getpid()}.txt")
    shutil.copyfile(COOKIE_FILE, tmp)
    tmp.chmod(0o600)
    return ["--cookies", str(tmp)]


LOCKED = re.compile(r"404|not found|private video|video unavailable|members-only|join this channel|do not have permission"
                    r"|access denied|need access", re.I)
CLAUDE = str(Path.home() / ".local/bin/claude")


def log(msg):
    line = f"{datetime.datetime.now():%Y-%m-%d %H:%M} {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def notify(msg):
    """Telegram via Hermes on the VPS, desktop notification on the laptop; never fails the run."""
    cmd = ["hermes", "send", "-q", "-t", "telegram", f"🎬 yupa: {msg}"] if HEADLESS else ["notify-send", "yupa", msg]
    try:
        subprocess.run(cmd, check=False, timeout=60, capture_output=True)
    except (OSError, subprocess.TimeoutExpired):
        pass


def claude_usage(_retry=True):
    """{'five_hour': pct, 'seven_day': pct, 'resets_at': iso} from the Claude subscription usage endpoint, or None.
    Uses Claude Code's own OAuth login (~/.claude/.credentials.json); the token stays fresh because claude -p runs often."""
    import json, urllib.error, urllib.request
    try:
        tok = json.loads((Path.home() / ".claude/.credentials.json").read_text())["claudeAiOauth"]["accessToken"]
        req = urllib.request.Request("https://api.anthropic.com/api/oauth/usage", headers={
            "Authorization": f"Bearer {tok}", "anthropic-beta": "oauth-2025-04-20", "User-Agent": "yupa-daily"})
        try:
            d = json.load(urllib.request.urlopen(req, timeout=20))
        except urllib.error.HTTPError as e:
            if e.code != 401 or not _retry:
                raise
            # token expired during a pause; any real CLI call refreshes it (auth status does not). Tiny Haiku ping.
            subprocess.run([CLAUDE, "-p", "Reply with OK", "--model", "haiku"], capture_output=True, timeout=120)
            return claude_usage(_retry=False)
        return {"five_hour": (d.get("five_hour") or {}).get("utilization"),
                "seven_day": (d.get("seven_day") or {}).get("utilization"),
                "resets_at": (d.get("seven_day") or {}).get("resets_at")}
    except Exception as e:
        log(f"usage check failed ({type(e).__name__}: {e}); keeping the current pace")
        return None


def pace_hours(usage, current):
    """Hours between lectures given the latest usage (None = unknown -> keep the current pace)."""
    if not usage or usage.get("seven_day") is None:
        return current
    return SLOW_HOURS if usage["seven_day"] >= WEEKLY_LIMIT_PCT else EVERY_HOURS


def slug(s):
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:60]


def desktop_session_active():
    """Brave's cookie key lives in the GNOME keyring, which is only unlocked after you log in."""
    r = subprocess.run(["loginctl", "show-user", os.environ.get("USER", ""), "-p", "State", "--value"],
                       capture_output=True, text=True)
    return r.stdout.strip() == "active"


def save(rows):
    tmp = QUEUE.with_suffix(".tmp")
    with open(tmp, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    tmp.replace(QUEUE)


def write_index(rows):
    """out/index.md: every queued course/channel with links to finished articles (view.py out renders it)."""
    lines = ["# Lecture notes", "", f"{sum(r['status'] == 'done' for r in rows)} / {len(rows)} lectures done", ""]
    for cat in dict.fromkeys(r["category"] for r in rows):
        lines += [f"## {cat.upper()}", ""]
        for course in dict.fromkeys(r["course"] for r in rows if r["category"] == cat):
            done = [r for r in rows if r["course"] == course and r["category"] == cat and r["status"] == "done"]
            total = sum(r["course"] == course and r["category"] == cat for r in rows)
            if not done:
                lines.append(f"- {course} (0/{total})")
                continue
            lines.append(f"- **{course}** ({len(done)}/{total})")
            lines += [f"  - [{r['session']}]({out_dir(r).relative_to(ROOT / 'out')}/article.md)" for r in done]
        lines.append("")
    (ROOT / "out/index.md").write_text("\n".join(lines))


def is_youtube(r):
    return r["category"].startswith("sango")


def video_url(r, vid):
    return f"https://www.youtube.com/watch?v={vid}" if is_youtube(r) else f"https://drive.google.com/file/d/{vid}/view"


def out_dir(r):
    return ROOT / "out/sango" / r["id"] if is_youtube(r) else ROOT / "out/c4" / slug(r["course"]) / f"{int(r['n']):02d}"


class Transient(Exception):
    """Rate limit, bot check, bad cookies, disk: not the video's fault -> retry at the next slot."""


def accessible_id(r):
    """First id that opens for this account: the chosen section, then the same session in other sections.
    Returns None only when every copy is definitively locked; raises Transient for anything else."""
    for vid in [r["id"], *r.get("alt_ids", "").split()]:
        p = subprocess.run([shutil.which("yt-dlp") or "yt-dlp", "--js-runtimes", "node", *auth_args(),
                            "--print", "id", video_url(r, vid)],
                           capture_output=True, text=True, timeout=300)
        if p.returncode == 0:
            return vid
        err = (p.stderr.strip().splitlines() or ["?"])[-1]
        if "no longer valid" in p.stderr or "cookies" in err.lower():
            # YouTube rotated/invalidated the exported login: every members-only video would look "locked"
            raise Transient("LOGIN EXPIRED: " + err[:150])
        if not LOCKED.search(err):
            raise Transient(err[:200])
    return None


def run_lecture(r, vid):
    out, url = out_dir(r), video_url(r, vid)
    log(f"start {r['category']} | {r['course']} #{r['n']} | {r['session']} -> {out}")
    lang = ["--lang", "hi"] if is_youtube(r) else []   # Sango talks are Hindi/English; articles are written in English
    try:
        subprocess.run([sys.executable, "yupa.py", url, "--out", str(out), *auth_args(), *lang],
                       cwd=ROOT, check=True, timeout=4 * 3600)
    except BaseException:
        (out / "video.mp4").unlink(missing_ok=True)   # failed runs used to leave multi-GB videos behind
        raise
    if is_youtube(r):
        context = (f"Context: a members-only {CHANNEL} YouTube video ({url}), mostly Hindi; write the article in English.\n"
                   f"- Title: {r['session']}\n- Published: {r['term']}")
    else:
        context = (f"Context: this is a recorded MBA-style class, not a YouTube video.\n"
                   f"- Course: {r['course']} ({r['category']}, {r['term']}), session {r['n']}: {r['session']}\n"
                   f"- Instructor(s): {' / '.join(r['master'].split(chr(10)))}\n"
                   "Use the session name and course as the article's title and source line "
                   '(the Drive title is just "Session-N"; do not link the Drive URL).')
    prompt = f"""Follow the yupa skill (.claude/skills/yupa/SKILL.md) from step 2 for the lecture already extracted in {out}.
{context}
Put contact sheets in {out}/sheets/ (not a scratchpad). Skip the skill's "Show" step: do not run view.py.
If the video ends in a course/product pitch, keep it to one short labelled section.
Write {out}/article.md and stop. Reply with one line: frames used vs extracted."""
    res = subprocess.run([CLAUDE, "-p", prompt, "--model", MODEL, "--permission-mode", "acceptEdits",
                          "--allowedTools", "Read", "Write", "Edit", "Glob", "Grep",
                          "Bash(ffmpeg:*)", "Bash(ls:*)", "Bash(mkdir:*)", "Bash(sed:*)", "Bash(grep:*)", "Bash(wc:*)"],
                         cwd=ROOT, capture_output=True, text=True, timeout=2 * 3600)
    log(f"claude exit {res.returncode}: {res.stdout.strip()[-300:]}")
    if res.returncode or not (out / "article.md").exists():
        raise RuntimeError(f"no article written: {res.stderr.strip()[-300:]}")
    (out / "video.mp4").unlink(missing_ok=True)
    shutil.rmtree(out / "sheets", ignore_errors=True)
    used = set(re.findall(r"frames/(\d+\.jpg)", (out / "article.md").read_text()))
    for f in (out / "frames").glob("*.jpg"):      # ~300 per lecture; only the embedded ones are worth keeping
        if f.name not in used:
            f.unlink()


def main():
    force = "--force" in sys.argv
    only = set(sys.argv[sys.argv.index("--only") + 1].split(",")) if "--only" in sys.argv else None
    now = datetime.datetime.now()
    today = now.date().isoformat()
    with open(C4 / ".lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return print("already running")
        current = int(PACE.read_text()) if PACE.exists() else EVERY_HOURS
        usage = claude_usage()
        hours = pace_hours(usage, current)
        if usage:
            log(f"claude usage: 5h {usage['five_hour']}%, week {usage['seven_day']}% (resets {usage['resets_at']}) -> every {hours}h")
        if hours != current:
            PACE.write_text(str(hours))
            log(f"pace change -> every {hours}h (weekly usage {usage['seven_day']:.0f}%)")   # logged, not messaged: failures only
        if usage and (usage.get("five_hour") or 0) >= FIVE_HOUR_SKIP_PCT and not force:
            return print(f"5-hour Claude window at {usage['five_hour']}%; skipping this slot")
        if not force and not only and STAMP.exists():
            try:
                last = datetime.datetime.fromisoformat(STAMP.read_text().strip())
            except ValueError:
                last = now - datetime.timedelta(hours=hours)   # old date-only stamp from the one-a-day version
            if now - last < datetime.timedelta(hours=hours) - datetime.timedelta(minutes=5):
                return print(f"last lecture started {last:%H:%M}; next one after {last + datetime.timedelta(hours=hours):%H:%M}")
        if not HEADLESS and not desktop_session_active():
            return print("not logged in to the desktop yet; will retry next hour")
        free_gb = shutil.disk_usage(ROOT).free / 1e9
        if free_gb < MIN_FREE_GB:
            notify(f"only {free_gb:.1f} GB free on the server; pausing lectures until space is freed")
            return print(f"low disk: {free_gb:.1f} GB")
        rows = list(csv.DictReader(open(QUEUE)))
        todo = None
        cands = [r for r in rows if not r["status"] and (not only or r["id"] in only) and r["category"].startswith(CATEGORIES)]
        cands.sort(key=lambda r: r["category"].startswith("sango") == (now.hour % 2 == 1))   # stable: queue order kept inside each group
        for r in cands:
            try:
                vid = accessible_id(r)
            except Transient as e:
                log(f"access check hit a temporary error ({e}); retrying next slot")
                if str(e).startswith("LOGIN EXPIRED") and not (C4 / "login_alerted").exists():
                    (C4 / "login_alerted").write_text(today)   # one alert, not one per hour; delete after re-export
                    notify("YouTube login on the server expired, so lectures are paused. Re-export the cookies (ask Claude).")
                return
            if vid:
                todo = r
                break
            r["status"], r["done_on"] = "noaccess", today
            log(f"noaccess {r['course']} #{r['n']} ({r['id']})")
            save(rows)
        if not todo:
            write_index(rows)
            return print("queue finished")
        STAMP.write_text(now.isoformat(timespec="minutes"))   # set before running: a failure still uses the slot
        try:
            run_lecture(todo, vid)
            todo["status"], todo["done_on"] = "done", today
            # push to the VPS learning library (OpenClaw's daily lesson); a sync failure never fails the lecture
            sync = subprocess.run([sys.executable, str(ROOT / "vps/sync.py")], capture_output=True, text=True, timeout=600)
            log(f"vps sync exit {sync.returncode}: {(sync.stdout or sync.stderr).strip()[-200:]}")
        except Exception as e:
            todo["status"], todo["done_on"] = "failed", today
            log(f"FAILED {todo['course']} #{todo['n']}: {e}")
            notify(f"Lecture failed: {todo['course']} #{todo['n']} (see c4/daily.log)")
        save(rows)
        write_index(rows)


if __name__ == "__main__":
    main()
