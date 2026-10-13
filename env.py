"""Load KEY=VALUE lines from .env files (repo root, then cwd) into os.environ without overriding real env vars."""
import os
from pathlib import Path

def load(*dirs):
    for d in (*dirs, Path(__file__).resolve().parent):
        f = Path(d) / ".env"
        try:
            lines = f.read_text().splitlines()
        except OSError:   # missing or unreadable (e.g. /root on the laptop)
            continue
        for line in lines:
            k, sep, v = line.partition("=")
            if sep and not k.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip().strip("'\""))
