# yupadata

Personal values (notes domain, access email, channel name, C4 sheet id, VPS host) live in the gitignored `.env` (template `.env.example`); `$VARS` below refer to it. `env.py` loads it; the VPS has its own copy at `/root/yupadata/.env` and `/root/learning/.env`.

## yupa: video → illustrated article + quiz
`python3 yupa.py <url> [--lang hi]` → `out/<id>/timeline.md` + `frames/`, then follow the `yupa` skill (`.claude/skills/yupa/SKILL.md`) to write `out/<id>/article.md`.
- Frames: ffmpeg scene cuts (`--scene`, `--min-gap`, `--max-gap`), shot 0.5s *before* the next cut so code is typed and charts are drawn.
- Captions: YouTube json3 subs via yt-dlp (needs `--js-runtimes node`; yt-dlp installed via `uv tool install "yt-dlp[default]"`).
- Members-only videos: `--cookies-from-browser brave+gnomekeyring` (user is logged in on Brave; yt-dlp installed with `--with secretstorage` to decrypt Brave cookies)
- View: `python3 view.py out/<id>` renders `article.md` to `article.html` and opens it
- Tests: `python3 -m pytest -q test_yupa.py`

YouTube → knowledge workflow. Transcription and Q&A go through Gemini Notebook (formerly NotebookLM), which is the preferred transcriber.

## Tools (installed, user scope)
- `~/.local/bin/nlm` CLI + MCP server `gemini-notebook-mcp` (`uv tool install notebooklm-mcp-cli`)
- Skill: `nlm-skill` — load it before running nlm commands
- Auth: profile `default` (Google cookies). On auth errors: `nlm login`, check with `nlm login --check`

## Workflow
```bash
nlm notebook list
nlm notebook create "Topic"
nlm source add <nb_id> --youtube <url> --wait       # repeat --youtube for several videos
nlm notebook query <nb_id> "question"               # cited answer; prefer this, it's cheaper
nlm source list <nb_id> --json
nlm source content <source_id> -o transcript.md     # raw transcript, only when full text is needed
```

## Known limits
- YouTube sources are captions only: no visuals (charts, slides, on-screen text).
- For visuals, planned: Gemini API video understanding (pass the YouTube URL directly), then add the merged transcript back as a `--text` source. Needs `GEMINI_API_KEY` (not set up yet).
- Many videos are in Hindi; transcripts come back in Hindi. Translate on request.
- Free tier: ~50 queries/day. Check with `nlm usage`.

## Notebooks
- Trading Psychology and the Myth of Strategy: `2da10f73-e25e-4cb9-8937-c3c3fbed5047` (2 Hindi trading videos)

## Imbalance bot (planned)
Spec: `docs/imbalance-bot-spec.md`. Algo implementation of Ravindra Rokade's volume-imbalance intraday strategy (from the two articles in `out/`). Nothing implemented yet; 🟡 params in §10 are interpretations that need backtesting.

## Status log
- 2026-09-27: yupa built and tested (Python in 100s; 2 Rokade trading videos → `out/LsT0V2AgPak`, `out/-3HD0quIvMk`, cross-linked). Bot spec v0.2 in `docs/`.
- 2026-09-28: **$SANGO_CHANNEL "Stock Market Masterclass"** (members-only, 3:02:29, Hindi, the channel host) → `out/sango/14UMDouIYDo/article.md` done (395 frames → 25 sheets → 16 used).
- 2026-10-02: Notes site live at $NOTES_DOMAIN (private, Cloudflare Access, 20 articles, Telegram lessons link to it). VPS YouTube login had expired (VPS Brave profile was opened) → re-exported; pace now 1 lecture/hour. Queue: Sango 4/180 done, C4 HR 7 + Finance 6 done, 6 HR noaccess (C4 Drive 404 on personal account), weekly Claude usage 20%.
- 2026-10-11: Sango members-only done (180/180). Added 769 public Sango videos (`sango-public`, ≥5 min, from `c4/sango_all.txt`) to the queue; they run automatically (CATEGORIES=sango). Lesson Telegram is now ONE message/day with ONE lesson (afternoon/evening jobs paused; learning jobs pinned to copilot gpt-4.1). `faster-whisper` installed on the VPS (av pinned <17) for caption-less videos. C4 still waits: 13/513 done.

## C4 lecture queue (daily automation)
Source: Google Sheet "C4 Recordings" (`$C4_SHEET_ID`, Drive video links). `c4/all_rows.csv` = every row; `c4/build_queue.py` → `c4/queue.csv` (513 lectures, one section per course, order Sango money → Sango other → C4 HR → Ops → Finance → Tech → Other; `CATEGORIES` in daily.py limits which run (now Sango only; C4 waits for the user); status ""/done/failed/noaccess).
- Runner: `c4/daily.py` (one lecture every hour (was 2 h; sped up 2026-10-02 to finish Sango); slows to 1/day when Claude weekly usage ≥ 70%, skips a slot when the 5-hour window ≥ 90%; usage logged each run; needs desktop login for Brave cookies; model knob `MODEL`). Output `out/c4/<course>/<nn>/article.md`, index `out/index.md`. Log `c4/daily.log`.
- Schedule: systemd user timer `yupa-daily.timer` (hourly + 5 min after boot, Persistent). `systemctl --user list-timers`, `journalctl --user -u yupa-daily`.
- Manual: `python3 c4/daily.py --force`. Pause: `systemctl --user disable --now yupa-daily.timer`.

## Daily lesson on Telegram (Hermes, VPS)
- VPS `/root/learning/`: `library/` (articles + embedded frames, synced by `vps/sync.py`, which `c4/daily.py` runs after each lecture), `learn.py` (tracker + SM-2 spaced repetition; source `vps/learn.py`, tests `vps/test_learn.py`), `learn.db`.
- Hermes (not OpenClaw): skill `~/.hermes/skills/productivity/learning/SKILL.md` (v2: one theme/day, 3 messages, accountability), pre-scripts `~/.hermes/scripts/learning_slot{1,2,3}.py` → `learn.py slot N`, cron jobs `learning-morning/afternoon/evening` at 05:30/09:30/14:30 UTC = 11:00/15:00/20:00 IST, deliver telegram. Model: Copilot gpt-4.1. Streak = days with a graded quiz answer or `learn.py homework`.
- Check: `hermes cron list`, `hermes cron runs <id>`, output in `~/.hermes/cron/output/<id>/`. Reply to the Telegram message with quiz answers; Hermes grades via `learn.py pending/grade`.
- Phase 2 (not done): Notion, OneNote, Upsurge (upsurge.club course platform) as extra sources.

## Coding via Hermes → Claude Code (VPS)
- `/root/bin/cc-task <dir> "<task>" [--write] [--model opus] [--resume <session>]`: runs `claude -p` in the background (systemd-run), result to Telegram via `hermes send`; logs `/root/cc-tasks/<id>.json`. Read-only unless `--write`; never pushes/deletes/restarts.
- Hermes skill `~/.hermes/skills/productivity/claude-coder/SKILL.md` tells Hermes to use it (and to ask before push/delete/restart/credentials).

## Notes site: $NOTES_DOMAIN (private, VPS)
- `vps/notes_site.py` builds /var/www/notes from /root/learning/library after every ingest (`vps/sync.py` runs it). URLs `/sango/<title>/`, `/c4/<course>/<nn>-<session>/`, `/youtube/<title>/`; stored in `/root/learning/slugs.json`, **never change once assigned** (Telegram links). Index pages + full-text search (`search.json`).
- Lesson messages: `learn.py url_of()` → `🔗 Read: <url>`; the Hermes learning skill keeps the links verbatim.
- Privacy: Cloudflare proxied DNS + Cloudflare Access (email one-time PIN, $ACCESS_EMAIL only, 1-month session). Origin: nginx (`vps/deploy/notes.nginx`) allows only Cloudflare IPs and checks the Access JWT via `vps/access_check.py` (`notes-access.service`, port 8091, env `/root/.secrets/notes-access.env`: CF_TEAM_DOMAIN, CF_ACCESS_AUD). TLS: certbot dns-cloudflare, token in `/root/.secrets/cloudflare.ini`.
- Members-only and college content: never make this site public.
- VPS YouTube login = `/root/yupadata/cookies.txt`, exported from the laptop Brave profile **"VPS"** (`yt-dlp --cookies-from-browser "brave+gnomekeyring:VPS" --cookies f.txt …`). **Never open that profile**: opening it rotates the cookies and logs the VPS out (happened 2026-10-02; symptom: every Sango video says "members on level: Platinum", plus a LOGIN EXPIRED Telegram alert). Fix = re-export with the profile closed, scp, `rm c4/login_alerted`.
