#!/usr/bin/env python3
"""YouTube video -> timeline.md (timestamped transcript interleaved with scene-change screenshots).

Usage: yupa.py <youtube-url> [--lang en] [--scene 0.15] [--min-gap 5] [--max-gap 30]
Output: out/<video_id>/{video.mp4, frames/*.jpg, timeline.md, info.json}
The article + quiz are written afterwards by Claude (see .claude/skills/yupa/SKILL.md).
"""
import argparse, glob, json, re, shutil, subprocess, sys
from pathlib import Path

YTDLP = shutil.which("yt-dlp") or str(Path.home() / ".local/bin/yt-dlp")


def mmss(t):
    t = int(t)
    return f"{t // 3600}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def download(url, out, lang, auth):
    out.mkdir(parents=True, exist_ok=True)
    base = [YTDLP, url, "-o", str(out / "video.%(ext)s"), "--js-runtimes", "node", *auth,
            "-f", "bv*[height<=720]+ba/b[height<=720]/b", "-S", "res:720,+size", "--merge-output-format", "mp4",
            "--write-info-json"]
    subs = ["--write-subs", "--write-auto-subs", "--sub-langs", f"{lang},{lang}-orig,{lang}.*", "--sub-format", "json3/vtt/best"]
    if subprocess.run(base + subs).returncode:
        # YouTube 429s the caption request on some videos and that aborts the whole download: retry without
        # captions, load_captions() then falls back to whisper
        print("download with captions failed; retrying without them (whisper will transcribe)", file=sys.stderr)
        subprocess.run(base, check=True)
    Path(glob.glob(str(out / "video.info.json"))[0]).rename(out / "info.json")


def vtt_seconds(ts):
    h, m, sec = (["0"] + ts.split(":"))[-3:]
    return int(h) * 3600 + int(m) * 60 + float(sec)


def parse_vtt(text):
    """WebVTT -> [(start_sec, text)], dropping inline tags and the rolling duplicates auto-captions repeat."""
    cues, last = [], ""
    for block in re.split(r"\n\s*\n", text):
        m = re.search(r"(\d[\d:.]*\.\d+)\s+-->", block)
        if not m:
            continue
        body = " ".join(l for l in block.split("\n")[1:] if "-->" not in l)
        body = re.sub(r"<[^>]+>", "", body).strip()
        if body and body != last:
            cues.append((vtt_seconds(m.group(1)), body))
            last = body
    return cues


def whisper_cues(video, lang):
    """No captions at all: transcribe locally (slow on CPU, roughly real-time with the small model)."""
    from faster_whisper import WhisperModel
    segs, _ = WhisperModel("small", device="cpu", compute_type="int8").transcribe(str(video), language=lang, vad_filter=True)
    return [(s.start, s.text.strip()) for s in segs if s.text.strip()]


def load_captions(out, lang):
    """Captions -> [(start_sec, text)]: YouTube json3, else VTT (Google Drive), else local Whisper."""
    if files := sorted(glob.glob(str(out / "video.*.json3"))):
        cues = []
        for ev in json.loads(Path(files[0]).read_text())["events"]:
            text = "".join(s.get("utf8", "") for s in ev.get("segs", [])).strip()
            if text:
                cues.append((ev["tStartMs"] / 1000, text))
        return cues
    if files := sorted(glob.glob(str(out / "video.*.vtt"))):
        return parse_vtt(Path(files[0]).read_text())
    print("no captions; transcribing with faster-whisper", file=sys.stderr)
    return whisper_cues(out / "video.mp4", lang)


def scene_starts(video, scene, min_gap, max_gap):
    """Segment start times: scene changes at least min_gap apart, and never more than max_gap without one."""
    sel = (f"isnan(prev_selected_t)+gte(t-prev_selected_t\\,{max_gap})"
           f"+gt(scene\\,{scene})*gte(t-prev_selected_t\\,{min_gap})")
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(video), "-vf", f"select='{sel}',showinfo",
                        "-f", "null", "-"], capture_output=True, text=True, check=True)
    return [float(t) for t in re.findall(r"pts_time:([\d.]+)", r.stderr)]


def snapshot_times(starts, duration):
    """Shoot each segment just before the next cut: code is typed / chart lines are drawn by then."""
    ends = starts[1:] + [duration]
    return [max(s, e - 0.5) for s, e in zip(starts, ends)]


def grab_frames(video, frames_dir, times):
    shutil.rmtree(frames_dir, ignore_errors=True)  # stale frames from a previous run would mismatch the timeline
    frames_dir.mkdir()
    # ponytail: one ffmpeg spawn per frame (fast input seek); batch into one select filter if 500+ frames gets slow
    for n, t in enumerate(times, 1):
        subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", str(video),
                        "-frames:v", "1", "-q:v", "3", str(frames_dir / f"{n:04d}.jpg")], check=True)


def timeline(cues, times):
    """Attach each caption to the latest frame shown at or before it -> [(frame_time, text)]."""
    buckets = [[] for _ in times]
    i = 0
    for start, text in cues:
        while i + 1 < len(times) and times[i + 1] <= start:
            i += 1
        buckets[i].append(text)
    return [(t, " ".join(b).replace("\n", " ")) for t, b in zip(times, buckets)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--lang", default="en")
    ap.add_argument("--out", help="output dir (default out/<video id>)")
    ap.add_argument("--cookies-from-browser", help="e.g. firefox or chrome; for members-only videos you can watch")
    ap.add_argument("--cookies", help="Netscape cookies.txt (headless servers, e.g. the VPS)")
    ap.add_argument("--scene", type=float, default=0.15, help="ffmpeg scene-change threshold, lower = more frames")
    ap.add_argument("--min-gap", type=float, default=5, help="seconds; stops bursts during scrolling/animations")
    ap.add_argument("--max-gap", type=float, default=30, help="seconds; forces a frame on static screens")
    a = ap.parse_args()

    auth = (["--cookies", a.cookies] if a.cookies else
            ["--cookies-from-browser", a.cookies_from_browser] if a.cookies_from_browser else [])
    vid = subprocess.run([YTDLP, "--js-runtimes", "node", *auth, "--print", "id", a.url], capture_output=True, text=True, check=True).stdout.strip()
    out = Path(a.out) if a.out else Path("out") / vid
    if not (out / "video.mp4").exists():
        download(a.url, out, a.lang, auth)
    info = json.loads((out / "info.json").read_text())
    times = scene_starts(out / "video.mp4", a.scene, a.min_gap, a.max_gap)
    grab_frames(out / "video.mp4", out / "frames", snapshot_times(times, info["duration"]))

    md = [f"# {info['title']}", "", f"- URL: {info['webpage_url']}", f"- Channel: {info.get('channel')}",
          f"- Duration: {mmss(info.get('duration', 0))}", f"- Frames: {len(times)}", ""]
    if info.get("chapters"):
        md += ["## Chapters", *[f"- {mmss(c['start_time'])} {c['title']}" for c in info["chapters"]], ""]
    md += ["## Timeline", ""]
    for n, (t, text) in enumerate(timeline(load_captions(out, a.lang), times), 1):
        md += [f"### [{mmss(t)}] frames/{n:04d}.jpg", "", text or "_(no speech)_", ""]
    (out / "timeline.md").write_text("\n".join(md))
    print(out / "timeline.md")


if __name__ == "__main__":
    main()
