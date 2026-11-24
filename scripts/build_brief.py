#!/usr/bin/env python3
"""Build today's news brief.

1. Pulls headlines from the free RSS feeds listed in feeds.json.
2. Groups the same story from different outlets together and ranks stories by
   how many outlets are covering them (a simple, decent proxy for "relevant").
3. Drops stories already shown in the last few days, and keeps stock-market
   chatter to a minimum.
4. If an ANTHROPIC_API_KEY is set, asks Claude to pick the best stories and
   write short, plain summaries. Without a key it still works, using the
   outlets' own one-line descriptions.
5. Writes docs/data/latest.json (what the app shows) plus a dated archive copy.

Run:  python scripts/build_brief.py
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = ROOT / "scripts" / "feeds.json"
DATA_DIR = ROOT / "docs" / "data"
ARCHIVE_DIR = DATA_DIR / "archive"
HISTORY_FILE = DATA_DIR / "history.json"
TEAMS_FILE = ROOT / "scripts" / "my_teams.json"
MY_TEAMS_TOPIC = {"id": "myteams", "name": "My Teams", "emoji": "🏆", "default_on": True}

LOCAL_TZ = ZoneInfo(os.environ.get("BRIEF_TIMEZONE", "").strip() or "America/Chicago")
MODEL = os.environ.get("BRIEF_MODEL", "").strip() or "claude-sonnet-5-5"
MAX_AGE_HOURS = 36          # ignore anything older than this
HISTORY_DAYS = 5            # don't repeat a story shown in the last N days
ARCHIVE_DAYS = 14           # how many past days the app can look back on
CANDIDATES_PER_TOPIC = 12   # how many ranked stories per topic Claude chooses from

SOURCE_NAMES = {
    "npr.org": "NPR", "nytimes.com": "New York Times", "bbc.co.uk": "BBC",
    "bbc.com": "BBC", "cbsnews.com": "CBS News", "abcnews.go.com": "ABC News",
    "go.com": "ABC News", "abcnews.com": "ABC News", "bbci.co.uk": "BBC", "theguardian.com": "The Guardian",
    "aljazeera.com": "Al Jazeera", "arstechnica.com": "Ars Technica",
    "theverge.com": "The Verge", "espn.com": "ESPN", "cbssports.com": "CBS Sports", "yahoo.com": "Yahoo Sports",
}

MARKET_WORDS = re.compile(
    r"\b(stocks?|dow|s&p|nasdaq|wall street|shares?|earnings|investors?|"
    r"bond yields?|treasur(y|ies)|futures|rall(y|ies)|sell-?off|"
    r"market (close|open|rally)|bitcoin|crypto|ipo|quarterly (profit|results))\b",
    re.I,
)

# Service pieces and filler that aren't news: betting tips, fantasy advice, how-to-watch, quizzes.
FILLER_WORDS = re.compile(
    r"\b(odds|predictions?|best bets?|betting|picks|fantasy|how to watch|live stream|"
    r"where to watch|quiz|crossword|wordle|horoscope|deals? of the day|promo code|"
    r"wants to know|tell us|newsletter)\b",
    re.I,
)

STOPWORDS = set("""
a an the and or but if of to in on at by for with from as is are was were be been
being it its this that these those he she they them his her their we you your our
i me my not no yes do does did has have had will would can could should may might
new says say said after before over under about into out up down off than then
more most less least just also how what why who when where which while amid
first last year years day days week weeks report reports latest live update updates
news video watch photos analysis opinion here there now get gets got make makes
""".split())


# ---------------------------------------------------------------- feeds

def fetch(url: str) -> bytes | None:
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (compatible; daily-brief/1.0)",
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read()
    except Exception as e:  # one dead feed shouldn't stop the brief
        print(f"  ! could not fetch {url}: {e}", file=sys.stderr)
        return None


def fetch_json(url: str):
    raw = fetch(url)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        print(f"  ! bad JSON from {url}", file=sys.stderr)
        return None


def clean_text(s: str | None) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"^(This live blog is (now )?closed\.?|Live updates?:?)\s*", "", s, flags=re.I)
    s = re.sub(r"\s*(Continue reading|Read more|\.\.\.)\s*\.?\s*$", "", s, flags=re.I)
    return s


def parse_date(s: str | None) -> datetime | None:
    if not s:
        return None
    s = s.strip()
    try:
        d = parsedate_to_datetime(s)
    except Exception:
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except Exception:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(timezone.utc)


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def child_text(el, *names):
    for c in el:
        if local(c.tag) in names and (c.text or "").strip():
            return c.text
    return None


def parse_feed(raw: bytes, feed_url: str) -> list[dict]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as e:
        print(f"  ! bad XML from {feed_url}: {e}", file=sys.stderr)
        return []
    items = []
    for el in root.iter():
        kind = local(el.tag)
        if kind not in ("item", "entry"):
            continue
        title = clean_text(child_text(el, "title"))
        if not title:
            continue
        link = child_text(el, "link")
        if not link:  # Atom style <link href=".."/>
            for c in el:
                if local(c.tag) == "link" and c.get("href") and c.get("rel", "alternate") == "alternate":
                    link = c.get("href")
                    break
        desc = clean_text(child_text(el, "description", "summary", "content"))
        when = parse_date(child_text(el, "pubDate", "published", "updated", "date"))
        items.append({
            "title": title,
            "link": (link or "").strip(),
            "desc": desc[:600],
            "time": when,
            "rank": len(items),
        })
    return items


def source_name(url: str) -> str:
    host = urlparse(url).netloc.lower().removeprefix("www.")
    for dom, name in SOURCE_NAMES.items():
        if host == dom or host.endswith("." + dom):
            return name
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "gov"):
        return parts[-3].title()
    return parts[-2].title() if len(parts) >= 2 else host


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9']+", text.lower())
    return {w.strip("'") for w in words if len(w) > 2 and w not in STOPWORDS}


def overlap(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def same_story(a: set, b: set) -> bool:
    return len(a & b) >= 2 and overlap(a, b) >= 0.5


# ---------------------------------------------------------------- ranking

def collect(config: dict, now: datetime) -> list[dict]:
    jobs = [(t["id"], url) for t in config["topics"] for url in t["feeds"]]
    with ThreadPoolExecutor(max_workers=12) as pool:
        raws = list(pool.map(lambda j: fetch(j[1]), jobs))
    items = []
    ok = 0
    for (topic, url), raw in zip(jobs, raws):
        if not raw:
            continue
        parsed = parse_feed(raw, url)
        if parsed:
            ok += 1
        kept = 0
        for it in parsed:
            if it["time"] and now - it["time"] > timedelta(hours=MAX_AGE_HOURS):
                continue
            if not it["time"] and it["rank"] > 10:
                continue
            it["topic"] = topic
            it["source"] = source_name(it["link"] or url)
            it["tokens"] = tokens(it["title"])
            items.append(it)
            kept += 1
        print(f"  {topic:9} {kept:3}/{len(parsed):3} recent  {url}")
    print(f"Fetched {ok}/{len(jobs)} feeds, {len(items)} recent headlines")
    return items


def cluster(items: list[dict], config: dict) -> list[dict]:
    topic_order = [t["id"] for t in config["topics"]]
    clusters: list[dict] = []
    for it in sorted(items, key=lambda i: i["rank"]):
        for c in clusters:
            if same_story(it["tokens"], c["tokens"]):
                c["items"].append(it)
                c["tokens"] |= it["tokens"]
                break
        else:
            clusters.append({"items": [it], "tokens": set(it["tokens"])})

    low_market_topics = {t["id"] for t in config["topics"] if t.get("low_markets")}
    for c in clusters:
        its = c["items"]
        sources = {i["source"] for i in its}
        prominence = sum(1 / (1 + 0.25 * i["rank"]) for i in its)
        c["score"] = 3 * len(sources) + prominence
        topic_votes: dict[str, float] = {}
        for i in its:
            topic_votes[i["topic"]] = topic_votes.get(i["topic"], 0) + 1 / (1 + 0.25 * i["rank"])
        c["topic"] = max(topic_votes, key=lambda t: (topic_votes[t], -topic_order.index(t)))
        c["is_markets"] = bool(MARKET_WORDS.search(" ".join(i["title"] for i in its[:3])))
        # Skip filler and service pieces (betting tips, fantasy advice, how-to-watch, reader callouts).
        c["drop"] = any(FILLER_WORDS.search(i["title"]) for i in its[:2])
        if c["is_markets"]:
            # Day-to-day market moves are skipped; only genuinely big ones (many outlets) survive.
            c["score"] *= 0.35
            c["drop"] = c["drop"] or (c["topic"] in low_market_topics and len(sources) < 4)
        lead = min(its, key=lambda i: (i["rank"], -len(i["desc"])))
        c["headline"] = lead["title"]
        c["desc"] = max((i["desc"] for i in its), key=len, default="")
        c["time"] = max((i["time"] for i in its if i["time"]), default=None)
        seen, c["sources"] = set(), []
        for i in sorted(its, key=lambda i: i["rank"]):
            if i["source"] not in seen and i["link"]:
                seen.add(i["source"])
                c["sources"].append({"name": i["source"], "url": i["link"]})
    clusters.sort(key=lambda c: -c["score"])
    return clusters


def load_history(today: str) -> list[dict]:
    if not HISTORY_FILE.exists():
        return []
    hist = json.loads(HISTORY_FILE.read_text())
    cutoff = (datetime.fromisoformat(today) - timedelta(days=HISTORY_DAYS)).date().isoformat()
    # Ignore today's own entries so re-running on the same day doesn't hide everything.
    return [h for h in hist if cutoff <= h["date"] < today]


def is_repeat(c: dict, history: list[dict]) -> bool:
    t = tokens(c["headline"])
    return any(len(t & set(h["tokens"])) >= 3 and overlap(t, set(h["tokens"])) >= 0.6 for h in history)


# ---------------------------------------------------------------- summaries

def first_sentences(text: str, limit: int = 240) -> str:
    if len(text) <= limit:
        return text
    parts = re.split(r"(?<=[.!?])\s+", text)
    out = ""
    for p in parts:
        if len(out) + len(p) > limit and out:
            break
        out = (out + " " + p).strip()
    return out if len(out) <= limit + 40 else text[:limit].rsplit(" ", 1)[0] + "…"


def simple_brief(candidates: dict[str, list[dict]], config: dict) -> dict:
    stories = []
    for t in config["topics"]:
        for c in candidates.get(t["id"], [])[: t["max_stories"]]:
            stories.append({
                "id": c["id"], "topic": t["id"], "headline": c["headline"],
                "summary": first_sentences(c["desc"]) if c["desc"] and c["desc"] != c["headline"] else "",
                "why": "",
            })
    score = {c["id"]: c["score"] for cs in candidates.values() for c in cs}
    leads = {}
    for s in stories:  # the top story of each topic, most covered first
        leads.setdefault(s["topic"], s)
    top = sorted(leads.values(), key=lambda s: -score[s["id"]])[:8]
    return {"overview": [{"topic": s["topic"], "text": s["headline"]} for s in top], "stories": stories}


BRIEF_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["overview", "stories"],
    "properties": {
        "overview": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["topic", "text"],
                "properties": {"topic": {"type": "string"}, "text": {"type": "string"}},
            },
        },
        "stories": {
            "type": "array",
            "items": {
                "type": "object", "additionalProperties": False,
                "required": ["id", "headline", "summary", "why"],
                "properties": {
                    "id": {"type": "string"},
                    "headline": {"type": "string"},
                    "summary": {"type": "string"},
                    "why": {"type": "string"},
                },
            },
        },
    },
}

SYSTEM_PROMPT = """You are the editor of a short daily news brief for one busy reader in the U.S.
The reader wants to stay informed about the most important U.S. and world news in a few minutes,
like a bite-sized morning podcast, but without filler, hype, or repetition, and with very little
stock-market coverage.

You will get today's candidate stories, already grouped by topic and ranked by how many outlets
cover them, plus the headlines the reader already saw in the past few days.

Choose stories:
- Pick the stories that matter most: real consequences for people, major decisions, big events.
  Prefer stories several outlets are covering. Skip celebrity gossip, listicles, opinion pieces,
  how-to/service pieces, quizzes, live-blog shells and minor local crime.
- Fill each topic up to its limit with the best available candidates. Only pick fewer when the
  remaining candidates are genuinely not news (filler, gossip, service pieces).
- Do not pick a story the reader already saw unless there is a clearly new development; then
  write about only what is new.
- Business: favour things that affect everyday life (jobs, prices, big company decisions, tech
  shifts). Skip day-to-day stock, index, earnings or crypto moves unless truly historic.
- Use only facts present in the candidate text. Do not add outside facts, numbers or quotes.

Write each chosen story:
- headline: plain and specific, at most 12 words, no clickbait, no trailing period.
- summary: one or two short sentences (at most 45 words) saying what happened.
- why: at most 18 words on why it matters to the reader, or "" if obvious.

Also write overview: 5 or 6 one-sentence bullets (each at most 25 words) that together are
"the day in 60 seconds", drawn from your chosen stories, most important first, each tagged with
the story's topic id.

Neutral, calm, factual tone. Return stories using the candidate ids you were given."""


def ai_brief(candidates: dict[str, list[dict]], config: dict, history: list[dict]) -> dict | None:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY set: using outlet descriptions instead of AI summaries.")
        return None
    try:
        import anthropic
    except ImportError:
        print("anthropic package not installed: using simple summaries.")
        return None

    lines = []
    for t in config["topics"]:
        cs = candidates.get(t["id"], [])
        if not cs:
            continue
        lines.append(f"\n## Topic id: {t['id']} ({t['name']}), pick at most {t['max_stories']}")
        for c in cs:
            heads = "; ".join(dict.fromkeys(i["title"] for i in c["items"][:3]))
            srcs = ", ".join(s["name"] for s in c["sources"])
            lines.append(f"- id {c['id']} | outlets: {len(c['sources'])} ({srcs})\n"
                         f"  headlines: {heads}\n  text: {c['desc'][:400]}")
    seen = "\n".join(f"- {h['date']}: {h['headline']}" for h in history[-80:]) or "(none)"
    user = (f"Already shown in recent days:\n{seen}\n\nToday's candidates:\n" + "\n".join(lines))

    client = anthropic.Anthropic()
    kwargs = dict(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": BRIEF_SCHEMA}},
    )
    if MODEL in ("claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-2", "claude-fable-5-1"):
        # If a safety filter wrongly declines, the API retries on another model in the same call.
        kwargs.update(betas=["server-side-fallback-2026-07-01"], fallbacks="default")
    try:
        resp = client.beta.messages.create(**kwargs)
    except anthropic.AuthenticationError:
        print("! The Anthropic API key was rejected: check the ANTHROPIC_API_KEY secret.", file=sys.stderr)
        return None
    except anthropic.RateLimitError as e:
        print(f"! Anthropic rate limit or credit problem: {e}", file=sys.stderr)
        return None
    except anthropic.APIStatusError as e:
        print(f"! Anthropic API error {e.status_code}: {e}", file=sys.stderr)
        return None
    except anthropic.APIConnectionError as e:
        print(f"! Could not reach the Anthropic API: {e}", file=sys.stderr)
        return None

    if resp.stop_reason in ("refusal", "max_tokens"):
        print(f"! Claude stopped early ({resp.stop_reason}): using simple summaries.", file=sys.stderr)
        return None
    text = "".join(b.text for b in resp.content if b.type == "text")
    try:
        out = json.loads(text)
    except json.JSONDecodeError:
        print("! Could not read Claude's answer: using simple summaries.", file=sys.stderr)
        return None
    u = resp.usage
    print(f"AI summary by {resp.model}: {u.input_tokens} in / {u.output_tokens} out tokens")
    return out


def finalize(brief: dict, candidates: dict[str, list[dict]], config: dict) -> list[dict]:
    """Attach real links/sources and enforce topic limits, whatever the summary step returned."""
    by_id = {c["id"]: c for cs in candidates.values() for c in cs}
    limits = {t["id"]: t["max_stories"] for t in config["topics"]}
    counts: dict[str, int] = {}
    stories, used = [], set()
    for s in brief.get("stories", []):
        c = by_id.get(str(s.get("id")))
        if not c or c["id"] in used:
            continue
        topic = c["topic"]
        if counts.get(topic, 0) >= limits[topic]:
            continue
        counts[topic] = counts.get(topic, 0) + 1
        used.add(c["id"])
        stories.append({
            "id": c["id"],
            "topic": topic,
            "headline": (s.get("headline") or c["headline"]).strip(),
            "summary": (s.get("summary") or "").strip(),
            "why": (s.get("why") or "").strip(),
            "sources": c["sources"][:3],
            "time": c["time"].isoformat() if c["time"] else None,
            "_key": c["headline"],
        })
    order = [t["id"] for t in config["topics"]]
    stories.sort(key=lambda s: order.index(s["topic"]))
    return stories


# ---------------------------------------------------------------- main

def main() -> int:
    config = json.loads(FEEDS_FILE.read_text())
    now = datetime.now(timezone.utc)
    today = now.astimezone(LOCAL_TZ).date().isoformat()
    history = load_history(today)

    items = collect(config, now)
    if len(items) < 10:
        print("! Too few headlines fetched; keeping yesterday's brief.", file=sys.stderr)
        return 1

    clusters = cluster(items, config)
    candidates: dict[str, list[dict]] = {}
    repeats = 0
    for c in clusters:
        if c["drop"]:
            continue
        if is_repeat(c, history):
            repeats += 1
            continue
        bucket = candidates.setdefault(c["topic"], [])
        if len(bucket) < CANDIDATES_PER_TOPIC:
            c["id"] = f"{c['topic']}-{len(bucket) + 1}"
            bucket.append(c)
    print(f"{len(clusters)} distinct stories, {repeats} skipped as repeats")

    brief = ai_brief(candidates, config, history)
    used_ai = brief is not None
    stories = finalize(brief, candidates, config) if brief else []
    if not stories:
        used_ai = False
        brief = simple_brief(candidates, config)
        stories = finalize(brief, candidates, config)

    # My Teams: last night's wins and big news, added as its own topic.
    from my_teams import team_stories
    team = team_stories(TEAMS_FILE, datetime.fromisoformat(today), {
        "fetch": fetch, "fetch_json": fetch_json, "parse_feed": parse_feed, "tokens": tokens,
        "same_story": same_story,
        "is_repeat_title": lambda title: is_repeat({"headline": title}, history),
    })
    topics_out = [{k: t[k] for k in ("id", "name", "emoji", "default_on")} for t in config["topics"]]
    if TEAMS_FILE.exists() and json.loads(TEAMS_FILE.read_text()).get("teams"):
        topics_out.insert(0, MY_TEAMS_TOPIC)
    for s in team:
        s["_key"] = s["headline"]
    stories = team + stories

    topic_ids = {t["id"] for t in config["topics"]}
    overview = [o for o in brief.get("overview", []) if o.get("topic") in topic_ids and o.get("text")]

    out = {
        "date": today,
        "generated_at": now.isoformat(timespec="seconds"),
        "ai_summaries": used_ai,
        "topics": topics_out,
        "overview": overview,
        "stories": [{k: v for k, v in s.items() if not k.startswith("_")} for s in stories],
    }

    ARCHIVE_DIR.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(out, ensure_ascii=False, indent=1)
    (DATA_DIR / "latest.json").write_text(payload)
    (ARCHIVE_DIR / f"{today}.json").write_text(payload)

    # Keep a two-week archive and list it for the app.
    files = sorted(ARCHIVE_DIR.glob("*.json"), reverse=True)
    for old in files[ARCHIVE_DAYS:]:
        old.unlink()
    dates = [f.stem for f in files[:ARCHIVE_DAYS]]
    (DATA_DIR / "index.json").write_text(json.dumps({"dates": dates}))

    # Remember what was shown so tomorrow doesn't repeat it.
    full_hist = json.loads(HISTORY_FILE.read_text()) if HISTORY_FILE.exists() else []
    cutoff = (datetime.fromisoformat(today) - timedelta(days=HISTORY_DAYS + 2)).date().isoformat()
    full_hist = [h for h in full_hist if cutoff <= h["date"] < today]
    for s in stories:
        full_hist.append({"date": today, "headline": s["headline"],
                          "tokens": sorted(tokens(s["_key"]) | tokens(s["headline"]))})
    HISTORY_FILE.write_text(json.dumps(full_hist, ensure_ascii=False))

    print(f"Wrote brief for {today}: {len(stories)} stories, AI summaries: {used_ai}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
