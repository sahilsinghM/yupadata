#!/usr/bin/env python3
"""Copy finished articles (+ only the frames they embed) to the VPS learning library, then ingest there.

  out/<youtube id>/article.md   -> library/youtube/<id>/
  out/c4/<course>/<nn>/...      -> library/c4/<course>/<nn>/
Then builds the notes site. Run after each new article (c4/daily.py calls it) or by hand: python3 vps/sync.py
"""
import os, re, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import env; env.load()

ROOT = Path(__file__).resolve().parent.parent
HOST, REMOTE = os.environ.get("YUPA_VPS_HOST", "root@vps"), "/root/learning"   # "vps" = ssh alias in ~/.ssh/config
LOCAL = Path(REMOTE).exists()   # running on the VPS itself


def files():
    for art in sorted((ROOT / "out").glob("**/article.md")):
        rel = art.parent.relative_to(ROOT / "out")
        dest = rel if rel.parts[0] in ("c4", "sango") else Path("youtube") / rel
        refs = sorted(set(re.findall(r"\((frames/\d+\.jpg)\)", art.read_text())))
        for f in ["article.md", *refs]:
            if (art.parent / f).exists():
                yield art.parent / f, dest / f


def main():
    pairs = list(files())
    with tempfile.TemporaryDirectory() as tmp:
        stage = Path(tmp) / "library"
        for src, dest in pairs:          # hard-link into a mirror of the remote layout, then one rsync
            (stage / dest).parent.mkdir(parents=True, exist_ok=True)
            (stage / dest).hardlink_to(src)
        dst = "" if LOCAL else f"{HOST}:"
        subprocess.run(["rsync", "-aL" if LOCAL else "-azL", "--mkpath", f"{stage}/", f"{dst}{REMOTE}/library/"], check=True)
    subprocess.run(["rsync", "-a", str(ROOT / "vps/learn.py"), f"{dst}{REMOTE}/learn.py"], check=True)
    cmd = f"python3 {REMOTE}/learn.py ingest && python3 /root/yupadata/vps/notes_site.py"
    r = subprocess.run(cmd if LOCAL else ["ssh", "-o", "BatchMode=yes", HOST, cmd], shell=LOCAL,
                       capture_output=True, text=True, check=True)
    print(f"synced {len(pairs)} files; {' · '.join(r.stdout.split(chr(10))).strip(' ·')}")


if __name__ == "__main__":
    sys.exit(main())
