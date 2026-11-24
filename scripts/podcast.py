#!/usr/bin/env python3
"""Record today's brief as a short podcast with a free, open-source voice (Kokoro).

Reads docs/data/latest.json, writes docs/audio/brief.mp3 and docs/data/audio.json
(with chapter times, so the app can skip between stories and highlight the one playing).
Settings (voice, speed, which topics and in what order) live in scripts/podcast.json.

Run:  python scripts/podcast.py   (needs: pip install kokoro-onnx soundfile, plus the
      two model files in ./models, which the daily job downloads and caches)
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
OUT_DIR = ROOT / "build"   # not saved in the project; the daily job uploads it to the "podcast" release
SETTINGS = ROOT / "scripts" / "podcast.json"
MODELS = Path(os.environ.get("KOKORO_DIR", ROOT / "models"))

STORY_GAP = 0.7     # seconds of silence between stories
SECTION_GAP = 1.2   # ...and between topics

UNITS = [
    (r"(\d+)/(\d+)", r"\1 of \2"), (r"\bYDS\b", "yards"), (r"\bINT\b", "interception"),
    (r"\bCAR\b", "carries"), (r"\bREC\b", "catches"), (r"\bPTS\b", "points"), (r"\bREB\b", "rebounds"),
    (r"\bAST\b", "assists"), (r"\bBLK\b", "blocks"), (r"\bSTL\b", "steals"),
]


def spoken_stat(t: str) -> str:
    for pat, rep in UNITS:
        t = re.sub(pat, rep, t)
    t = re.sub(r"\b1 TD\b", "1 touchdown", t)
    t = re.sub(r"\b(\d+) TD\b", r"\1 touchdowns", t)
    return re.sub(r", ([^,]+)$", r" and \1", t)


def spoken_game(s: dict) -> str:
    m = re.match(r"^(✅|❌|➖)\s+(.+?)\s+(\d+),\s+(.+?)\s+(\d+)$", s["headline"])
    if not m:
        return s["headline"] + "."
    mark, me, a, opp, b = m.groups()
    if mark == "✅":
        line = f"The {me} beat the {opp}, {a} to {b}."
    elif mark == "❌":
        line = f"The {me} lost to the {opp}, {b} to {a}."
    else:
        line = f"The {me} and the {opp} tied at {a}."
    rec = re.search(r"Record (\d+)-(\d+)(?:-(\d+))?", s.get("summary", ""))
    if rec:
        line += f" They're now {rec.group(1)} and {rec.group(2)}" + (f" and {rec.group(3)}" if rec.group(3) else "") + "."
    if s.get("stat"):
        who, _, what = s["stat"].partition(":")
        line += f" {who.strip()} led the way with {spoken_stat(what.strip())}."
    return line


def clean(t: str) -> str:
    t = (t or "").replace("“", '"').replace("”", '"').replace("’", "'").replace("‘", "'")
    t = re.sub(r"\s+", " ", t).strip()
    return t if not t or t[-1] in ".!?\"'" else t + "."


def ordinal(n: int) -> str:
    return f"{n}{'th' if 11 <= n % 100 <= 13 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def build_script(brief: dict, settings: dict) -> list[dict]:
    topics = {t["id"]: t for t in brief["topics"]}
    order = [t for t in settings.get("topics", []) if t in topics] or [t["id"] for t in brief["topics"] if t.get("default_on")]
    day = datetime.fromisoformat(brief["date"])
    segs = [{"text": f"Good morning. Here's your Daily Brief for {day:%A}, {day:%B} {ordinal(day.day)}.",
             "label": "Intro", "gap": SECTION_GAP}]
    first = True
    for tid in order:
        stories = [s for s in brief["stories"] if s["topic"] == tid]
        if not stories:
            continue
        t = topics[tid]
        name = {"myteams": "your teams", "us": "U.S. news", "world": "world news"}.get(
            tid, re.sub(r"\s*\(light\)", "", t["name"], flags=re.I).replace("&", "and").lower())
        lead = f"First up, {name}." if first else f"Next, {name}."
        first = False
        for i, s in enumerate(stories):
            if tid == "myteams":
                text = spoken_game(s)
            else:
                text = " ".join(x for x in (clean(s["headline"]), clean(s.get("summary", "")),
                                            f"Why it matters: {clean(s['why'])}" if s.get("why") else "") if x)
                if i > 0:
                    joiner = "And finally," if i == len(stories) - 1 and i > 1 else ["Also,", "Meanwhile,"][(i - 1) % 2]
                    text = f"{joiner} {text}"
            if i == 0:
                text = f"{lead} {text}"
            segs.append({"text": text, "sid": s["id"], "topic": tid,
                         "label": f"{t['emoji']} {t['name']} · {i + 1} of {len(stories)}",
                         "gap": SECTION_GAP if i == len(stories) - 1 else STORY_GAP})
    segs.append({"text": "That's your brief. Have a great day.", "label": "Wrapping up", "gap": 0.3})
    return segs


HOST_PROMPT = """You are the host of a short daily news podcast for one listener: an adult who
wants to stay informed in a few minutes and enjoys sharp, witty, grown-up humor. You will get the
plain script of today's episode, one numbered segment at a time. Rewrite every segment so it sounds
like a smart friend talking, not a newsreader.

How to rewrite:
- Conversational and loose: contractions, plain words, short sentences, the occasional aside.
  Summarize; don't read the headline back word for word.
- Explain anything a busy person might not know, in a few words, woven in naturally: acronyms
  (say what they stand for or what the group does), people who aren't household names, places,
  jargon, and the one bit of background that makes the story make sense.
- Humor: witty, dry, sarcastic, a little irreverent, adult. Innuendo and the occasional mild swear
  word are fine. Only use a joke when it lands naturally inside the story; at most one quip per
  segment and skip it when nothing clever comes. Never joke about deaths, victims, disasters, war
  casualties, abuse or anyone's suffering; for those stories be warm and straight. Punch up at the
  powerful, not down. No forced puns, no "folks", no "buckle up".
- Facts: keep every fact accurate and only use facts from the segment, plus widely known general
  background (like what an acronym stands for). Never invent numbers, quotes or details.
- Sports recaps: keep the final score and the standout stat line, and make it sound like a fan
  talking. These are the listener's own teams, so cheer the wins and grumble a little at losses.
- Keep the flow: the intro welcomes the listener, the first segment of each topic introduces that
  topic, the rest flow on from the one before, and the last segment signs off with personality.
- Written to be spoken by a text-to-speech voice: no emojis, symbols, bullet points, parentheses
  or stage directions; write numbers the way you'd say them ("fifty-one to thirty" is fine, so is
  "51 to 30"); spell out abbreviations that wouldn't be read correctly.
- Length: roughly 30 to 80 words per segment. The whole episode should stay around five to seven
  minutes.

Return one rewritten segment for every input segment, with the same index."""

PODCAST_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["segments"],
    "properties": {"segments": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["index", "text"],
        "properties": {"index": {"type": "integer"}, "text": {"type": "string"}},
    }}},
}


def punch_up(segs: list[dict]) -> list[dict]:
    """Have Claude rewrite the script as a casual, witty host. Falls back to the plain script."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY: podcast uses the plain script.")
        return segs
    try:
        import anthropic
    except ImportError:
        return segs
    model = os.environ.get("PODCAST_MODEL", "").strip() or os.environ.get("BRIEF_MODEL", "").strip() or "claude-opus-5-5"
    numbered = "\n\n".join(f"[{i}] ({s.get('label', '')})\n{s['text']}" for i, s in enumerate(segs))
    kwargs = dict(
        model=model,
        max_tokens=16000,
        system=HOST_PROMPT,
        messages=[{"role": "user", "content": f"Today's plain script, {len(segs)} segments:\n\n{numbered}"}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": PODCAST_SCHEMA}},
    )
    if model in ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1"):
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    try:
        resp = anthropic.Anthropic().beta.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        print("! Anthropic key rejected: podcast uses the plain script.", file=sys.stderr)
        return segs
    except anthropic.RateLimitError as e:
        print(f"! Anthropic rate limit or credit problem ({e}): plain script.", file=sys.stderr)
        return segs
    except anthropic.APIStatusError as e:
        print(f"! Anthropic API error {e.status_code}: plain script.", file=sys.stderr)
        return segs
    except anthropic.APIConnectionError as e:
        print(f"! Could not reach Anthropic ({e}): plain script.", file=sys.stderr)
        return segs
    if resp.stop_reason in ("refusal", "max_tokens"):
        print(f"! Host rewrite stopped early ({resp.stop_reason}): plain script.", file=sys.stderr)
        return segs
    try:
        out = json.loads("".join(b.text for b in resp.content if b.type == "text"))
        rewritten = {int(x["index"]): x["text"].strip() for x in out["segments"] if x.get("text", "").strip()}
    except (ValueError, KeyError, TypeError):
        print("! Could not read the host rewrite: plain script.", file=sys.stderr)
        return segs
    for i, seg in enumerate(segs):
        if i in rewritten:
            seg["plain"] = seg["text"]
            seg["text"] = rewritten[i]
    print(f"Host rewrite by {resp.model}: {len(rewritten)}/{len(segs)} segments, "
          f"{resp.usage.input_tokens} in / {resp.usage.output_tokens} out tokens")
    return segs


def main() -> int:
    brief = json.loads((DATA / "latest.json").read_text())
    settings = json.loads(SETTINGS.read_text()) if SETTINGS.exists() else {}
    if not settings.get("enabled", True):
        print("Podcast is turned off in scripts/podcast.json.")
        return 0
    try:
        from kokoro_onnx import Kokoro
        import soundfile as sf
    except ImportError as e:
        print(f"! Podcast skipped, voice library missing: {e}", file=sys.stderr)
        return 0
    model = MODELS / "kokoro-v1.0.int8.onnx"
    voices = MODELS / "voices-v1.0.bin"
    if not model.exists() or not voices.exists():
        print(f"! Podcast skipped, voice model files not found in {MODELS}", file=sys.stderr)
        return 0

    kokoro = Kokoro(str(model), str(voices))
    voice = settings.get("voice", "af_heart")
    speed = float(settings.get("speed", 1.0))
    segs = build_script(brief, settings)
    if settings.get("host_style", True):
        segs = punch_up(segs)

    started = time.time()
    pieces, chapters, t = [], [], 0.0
    sr = 24000
    for seg in segs:
        audio, sr = kokoro.create(seg["text"], voice=voice, speed=speed, lang="en-us")
        chapters.append({"t": round(t, 2), "label": seg["label"], "sid": seg.get("sid"), "topic": seg.get("topic")})
        gap = np.zeros(int(sr * seg["gap"]), dtype=np.float32)
        pieces += [audio.astype(np.float32), gap]
        t += len(audio) / sr + seg["gap"]
    full = np.concatenate(pieces)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.glob("brief-*.mp3"):
        old.unlink()
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    out = OUT_DIR / f"brief-{stamp}.mp3"
    sf.write(out, full, sr, format="MP3", bitrate_mode="CONSTANT", compression_level=0.75)
    repo = os.environ.get("GITHUB_REPOSITORY", "croyal008/daily-brief")
    # audio.json goes to build/ too; the job copies it into the site only after the upload succeeds.
    (OUT_DIR / "audio.json").write_text(json.dumps({
        "date": brief["date"],
        "generated_at": brief["generated_at"],
        "url": f"https://github.com/{repo}/releases/download/podcast/{out.name}",
        "duration": round(t, 1),
        "voice": voice,
        "style": "host" if any("plain" in s for s in segs) else "plain",
        "chapters": chapters,
    }, ensure_ascii=False, indent=1))
    print(f"Podcast: {t / 60:.1f} min, {len(segs)} parts, voice {voice}, "
          f"{out.stat().st_size / 1e6:.1f} MB, made in {time.time() - started:.0f}s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
