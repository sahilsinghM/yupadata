---
name: yupa
description: Turn a long-form technical YouTube video (coding, trading, etc.) into an illustrated Markdown article with screenshots and a quiz. Use when the user gives a YouTube URL and wants notes, an article, a write-up, or a quiz from it.
---

# yupa: YouTube video → illustrated article + quiz

## 1. Extract
```bash
python3 yupa.py "<url>"                 # add --lang hi for Hindi-only videos
                                        # members-only: add --cookies-from-browser brave+gnomekeyring
```
It prints `out/<id>/timeline.md`: the title, the chapters, then one section per screenshot (`### [mm:ss] frames/NNNN.jpg`) with the speech that played while it was on screen.
If there are too few frames (static screen capture), rerun with `--scene 0.08 --max-gap 15`. If there are too many near-duplicates, use `--scene 0.3 --min-gap 10`.

## 2. Understand
Read `timeline.md` in full. Then **look at every frame** with Read. Batch them in parallel, around 10 per message. For each frame, note:
- what is on screen: code (transcribe the important lines exactly), chart (instrument, timeframe, indicators, drawn levels, the setup being pointed at), slide, diagram, terminal output, or just a talking head
- how it connects to what's being said at that moment, and anything shown that the speaker never says out loud

Write each note keyed by its filename as you read it. Never work out frame numbers from memory or from a combined image; mismatched captions are the easiest mistake to make here.

If there are more than 30 frames, sort them first using numbered contact sheets (16 frames per image, each tile labelled with its frame number):
```bash
ffmpeg -loglevel error -y -framerate 1 -i out/<id>/frames/%04d.jpg -vf "scale=400:-1,drawtext=text='%{eif\:n+1\:d\:4}':x=8:y=8:fontsize=36:fontcolor=yellow:box=1:boxcolor=black@0.7,tile=4x4" <scratchpad>/sheet%02d.jpg
```
Open **every** contact sheet, including the Q&A at the end; Q&A often has the most practical answers. Use the sheets only to *pick* frames: drop talking heads, and for a drawing that builds up over several frames, pick the most complete state. Then Read each picked frame at full size before writing about it. (Tested on a 48-min trading podcast: 133 frames → 9 sheets → 15 full reads.)

## 3. Write `out/<id>/article.md`
- An H1 title, then a line with source link, channel and duration, then a 3–5 bullet **TL;DR**.
- Sections follow the video's chapters (or natural topic shifts if there are none). Write it as an article that teaches, not a transcript recap: explain the *why*, and merge what was said with what was shown.
- Embed only the frames that carry information, as `![what it shows](frames/NNNN.jpg)` with a caption line `*[mm:ss] what to notice*`. Skip talking heads and duplicates.
- Code shown on screen → a fenced code block, transcribed from the frame, not paraphrased. Chart setups → name the entry, stop and target when they're shown.
- If the speech isn't in English, write the article in English anyway (keep key terms in their original language in parentheses where it helps).
- End with **Key takeaways**, then **Quiz**: 5–8 questions. Mix multiple choice, "what does this code print / what happens on this chart" (reference a frame), and one "explain why" question. Use exactly this layout per question (a learning tracker parses it):
  ```
  **1. Question text?**
  a) … b) … (options, if multiple choice)
  <details><summary>Answer</summary>Answer + one-line explanation.</details>
  ```

## 4. Show
Run `python3 view.py out/<id>`. It writes `article.html` next to the article and opens it in the browser.

## 5. Report
Give the path to `article.md`, the frame count used vs. extracted, and anything the video showed that you couldn't read clearly.
