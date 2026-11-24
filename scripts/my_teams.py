"""'My Teams': last night's wins and big news for the reader's own teams.

A team appears only when it (a) won a game yesterday, or (b) has big news today
(a trade, signing, injury, firing, clinching, etc., or a story many outlets cover).
Scores come from ESPN's public scoreboard; news comes from a Google News search.
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote_plus

LEAGUES = {
    "nfl": "football/nfl",
    "nba": "basketball/nba",
    "mlb": "baseball/mlb",
    "nhl": "hockey/nhl",
    "wnba": "basketball/wnba",
    "mls": "soccer/usa.1",
    "college-football": "football/college-football",
    "college-basketball": "basketball/mens-college-basketball",
}

BIG_NEWS = re.compile(
    r"\b(trade[sd]?|acquire[sd]?|sign(s|ed|ing)?|extension|contract|re-?signs?|released|waive[sd]|"
    r"fire[sd]|hire[sd]|names? .{0,20}(coach|manager|gm)|resign(s|ed)?|retire[sd]?|retirement|"
    r"injur(y|ies|ed)|out for (the )?season|torn|acl|surgery|suspen(ded|sion)|arrest(ed)?|"
    r"clinch(es|ed)?|eliminated|playoff berth|draft pick|no\.? ?1 pick|mvp|record-breaking|"
    r"breaks? (the )?record|sold|sale of the team|new stadium|relocat)",
    re.I,
)
SCORE_LINE = re.compile(r"\b\d{1,3}\s*[-–]\s*\d{1,3}\b")
FILLER = re.compile(r"\b(odds|predictions?|picks|betting|best bets?|fantasy|how to watch|live stream|mock draft|power rankings?|grades)\b", re.I)


def load_teams(path: Path) -> list[dict]:
    if not path.exists():
        return []
    teams = json.loads(path.read_text()).get("teams", [])
    good = []
    for t in teams:
        if t.get("name") and t.get("league") in LEAGUES:
            good.append(t)
        else:
            print(f"  ! skipping team entry {t}: needs a name and a league from {sorted(LEAGUES)}", file=sys.stderr)
    return good


def _matches(team: dict, comp_team: dict) -> bool:
    want = team["name"].lower()
    names = {
        (comp_team.get("displayName") or "").lower(),
        f"{comp_team.get('location', '')} {comp_team.get('name', '')}".strip().lower(),
    }
    return want in names


def last_night_win(team: dict, yesterday: datetime, fetch_json) -> dict | None:
    url = (f"https://site.api.espn.com/apis/site/v2/sports/{LEAGUES[team['league']]}/scoreboard"
           f"?dates={yesterday:%Y%m%d}&limit=400")
    if team["league"].startswith("college"):
        url += "&groups=50" if "basketball" in team["league"] else "&groups=80"
    data = fetch_json(url)
    if not data:
        return None
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        if not comp.get("status", ev.get("status", {})).get("type", {}).get("completed"):
            continue
        sides = comp.get("competitors", [])
        mine = next((c for c in sides if _matches(team, c.get("team", {}))), None)
        if not mine or len(sides) != 2:
            continue
        other = next(c for c in sides if c is not mine)
        if not mine.get("winner"):
            return None  # they played and didn't win: stay quiet
        my_name = mine["team"].get("shortDisplayName") or mine["team"].get("name") or team["name"]
        opp = other["team"].get("shortDisplayName") or other["team"].get("displayName", "their opponent")
        headline = f"{my_name} beat the {opp} {mine.get('score')}–{other.get('score')}"
        blurb = ""
        for h in comp.get("headlines", []) or []:
            blurb = (h.get("description") or h.get("shortLinkText") or "").strip()
            if blurb:
                break
        link = ""
        for l in ev.get("links", []) or []:
            if "recap" in (l.get("rel") or []) or "summary" in (l.get("rel") or []):
                link = l.get("href", "")
                if "recap" in l.get("rel", []):
                    break
        return {
            "headline": headline,
            "summary": blurb or f"Final score from last night: {my_name} {mine.get('score')}, {opp} {other.get('score')}.",
            "sources": [{"name": "ESPN", "url": link or f"https://www.espn.com/search/_/q/{quote_plus(team['name'])}"}],
        }
    return None


def big_news(team: dict, fetch, parse_feed, tokens, same_story, is_repeat_title) -> dict | None:
    q = quote_plus(f"\"{team['name']}\" when:1d")
    raw = fetch(f"https://news.google.com/rss/search?q={q}&hl=en-US&gl=US&ceid=US:en")
    if not raw:
        return None
    items = parse_feed(raw, "news.google.com")
    nick = team["name"].split()[-1].lower()
    groups: list[dict] = []
    for it in items[:40]:
        title, _, source = it["title"].rpartition(" - ")
        if not title:
            title, source = it["title"], "News"
        if nick not in title.lower() or FILLER.search(title) or SCORE_LINE.search(title):
            continue
        toks = tokens(title)
        for g in groups:
            if same_story(toks, g["tokens"]):
                g["sources"].setdefault(source, it["link"])
                g["tokens"] |= toks
                break
        else:
            groups.append({"title": title, "tokens": set(toks), "sources": {source: it["link"]},
                           "desc": it["desc"], "rank": it["rank"]})
    for g in groups:
        g["big"] = bool(BIG_NEWS.search(g["title"])) or len(g["sources"]) >= 4
    picks = [g for g in groups if g["big"] and not is_repeat_title(g["title"])]
    if not picks:
        return None
    best = max(picks, key=lambda g: (len(g["sources"]), -g["rank"]))
    return {
        "headline": best["title"],
        "summary": "",
        "sources": [{"name": n, "url": u} for n, u in list(best["sources"].items())[:3]],
    }


def team_stories(teams_file: Path, today_local: datetime, helpers: dict) -> list[dict]:
    teams = load_teams(teams_file)
    if not teams:
        return []
    yesterday = today_local - timedelta(days=1)
    out = []
    for team in teams:
        try:
            win = last_night_win(team, yesterday, helpers["fetch_json"])
            news = big_news(team, helpers["fetch"], helpers["parse_feed"], helpers["tokens"],
                            helpers["same_story"], helpers["is_repeat_title"])
        except Exception as e:  # never let one team break the brief
            print(f"  ! team {team['name']}: {e}", file=sys.stderr)
            continue
        for kind, s in (("win", win), ("news", news)):
            if s:
                s.update(id=f"team-{re.sub(r'[^a-z0-9]+', '-', team['name'].lower())}-{kind}",
                         topic="myteams", why="")
                out.append(s)
        print(f"  team {team['name']}: win={'yes' if win else 'no'}, big news={'yes' if news else 'no'}")
    return out
