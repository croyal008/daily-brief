"""'My Teams': a recap of yesterday's game for each of the reader's teams.

Each card has the same shape:
  headline  "✅ Spurs 118, Lakers 112"        (✅ win, ❌ loss, ➖ tie)
  summary   "Final/OT · vs. Lakers · Record 10-5"
  stat      "Victor Wembanyama: 32 PTS, 14 REB, 5 BLK"   (only when a performance stands out)
Teams that didn't play yesterday don't appear. Data comes from ESPN's public scoreboard.
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
BASKETBALL = {"nba", "wnba", "college-basketball"}
FOOTBALL = {"nfl", "college-football"}

# What counts as a standout line: (category, minimum yards/points, minimum TDs)
FOOTBALL_BARS = {"passingYards": (275, 3), "rushingYards": (100, 2), "receivingYards": (100, 2)}
BASKETBALL_MIN_POINTS = 20


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


def _matches(team: dict, ct: dict) -> bool:
    want = team["name"].lower()
    names = {
        (ct.get("displayName") or "").lower(),
        f"{ct.get('location', '')} {ct.get('name', '')}".strip().lower(),
        (ct.get("abbreviation") or "").lower(),
    }
    return want in names


def _num(s) -> float:
    m = re.search(r"-?\d+(\.\d+)?", str(s or ""))
    return float(m.group()) if m else 0.0


def _tds(display: str) -> int:
    m = re.search(r"(\d+)\s*TD", display or "")
    return int(m.group(1)) if m else 0


def _athlete(leader: dict) -> str:
    a = leader.get("athlete") or {}
    return a.get("displayName") or a.get("fullName") or a.get("shortName") or ""


def _my_leaders(comp: dict, mine: dict) -> dict[str, dict]:
    """Category name -> top leader entry for my team, from wherever ESPN put them."""
    out: dict[str, dict] = {}
    team_id = str((mine.get("team") or {}).get("id") or mine.get("id") or "")
    for cat in mine.get("leaders") or []:
        if cat.get("leaders"):
            out.setdefault(cat.get("name", ""), cat["leaders"][0])
    for cat in comp.get("leaders") or []:
        for l in cat.get("leaders") or []:
            lt = str((l.get("team") or {}).get("id") or "")
            if team_id and lt == team_id:
                out.setdefault(cat.get("name", ""), l)
                break
    return out


def standout(league: str, comp: dict, mine: dict) -> str:
    leaders = _my_leaders(comp, mine)
    if league in BASKETBALL:
        pts = leaders.get("points")
        if not pts or _num(pts.get("value") or pts.get("displayValue")) < BASKETBALL_MIN_POINTS:
            return ""
        who = _athlete(pts)
        rating = leaders.get("rating")
        if rating and _athlete(rating) == who and rating.get("displayValue"):
            return f"{who}: {rating['displayValue']}"
        parts = [f"{int(_num(pts.get('value') or pts.get('displayValue')))} PTS"]
        for cat, label in (("rebounds", "REB"), ("assists", "AST")):
            l = leaders.get(cat)
            if l and _athlete(l) == who:
                parts.append(f"{int(_num(l.get('value') or l.get('displayValue')))} {label}")
        return f"{who}: {', '.join(parts)}"
    if league in FOOTBALL:
        best, best_score = None, 0.0
        for cat, (yards_bar, td_bar) in FOOTBALL_BARS.items():
            l = leaders.get(cat)
            if not l:
                continue
            disp = l.get("displayValue", "")
            m = re.search(r"(\d+)\s*YDS", disp.replace(",", ""))
            yards = _num(l.get("value")) or (float(m.group(1)) if m else 0.0)
            score = max(yards / yards_bar, _tds(disp) / td_bar)
            if score >= 1 and score > best_score:
                best, best_score = l, score
        if best:
            return f"{_athlete(best)}: {best.get('displayValue', '')}".strip()
    return ""


def yesterdays_game(team: dict, yesterday: datetime, fetch_json) -> dict | None:
    league = team["league"]
    url = (f"https://site.api.espn.com/apis/site/v2/sports/{LEAGUES[league]}/scoreboard"
           f"?dates={yesterday:%Y%m%d}&limit=400")
    if league == "college-football":
        url += "&groups=80"   # all FBS games
    elif league == "college-basketball":
        url += "&groups=50"   # all Division I games
    data = fetch_json(url)
    if not data:
        return None
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        status = comp.get("status") or ev.get("status") or {}
        if not status.get("type", {}).get("completed"):
            continue
        sides = comp.get("competitors", [])
        mine = next((c for c in sides if _matches(team, c.get("team", {}))), None)
        if not mine or len(sides) != 2:
            continue
        other = next(c for c in sides if c is not mine)
        me = mine["team"].get("shortDisplayName") or mine["team"].get("name") or team["name"]
        opp = other["team"].get("shortDisplayName") or other["team"].get("name") or "Opponent"
        my_score, opp_score = mine.get("score", "?"), other.get("score", "?")
        if mine.get("winner"):
            mark = "✅"
        elif other.get("winner"):
            mark = "❌"
        else:
            mark = "➖"
        where = "vs." if mine.get("homeAway") == "home" else "at"
        detail = status.get("type", {}).get("shortDetail") or "Final"
        bits = [detail, f"{where} {opp}"]
        records = mine.get("records") or []
        if records and records[0].get("summary"):
            bits.append(f"Record {records[0]['summary']}")
        link = ""
        for l in ev.get("links", []) or []:
            rel = l.get("rel") or []
            if "recap" in rel:
                link = l.get("href", "")
                break
            if "summary" in rel and not link:
                link = l.get("href", "")
        found = _my_leaders(comp, mine)
        print("    leaders: " + "; ".join(f"{k}={_athlete(v)} {v.get('displayValue', '')}" for k, v in found.items()))
        try:
            stat = standout(league, comp, mine)
        except Exception as e:  # stats are a bonus; never lose the score over them
            print(f"  ! stat line for {team['name']}: {e}", file=sys.stderr)
            stat = ""
        return {
            "headline": f"{mark} {me} {my_score}, {opp} {opp_score}",
            "summary": " · ".join(bits),
            "stat": stat,
            "sources": [{"name": "ESPN recap", "url": link or
                         f"https://www.espn.com/search/_/q/{quote_plus(team['name'])}"}],
        }
    return None


def team_stories(teams_file: Path, today_local: datetime, helpers: dict) -> list[dict]:
    teams = load_teams(teams_file)
    yesterday = today_local - timedelta(days=1)
    out = []
    for team in teams:
        try:
            game = yesterdays_game(team, yesterday, helpers["fetch_json"])
        except Exception as e:  # never let one team break the brief
            print(f"  ! team {team['name']}: {e}", file=sys.stderr)
            continue
        print(f"  team {team['name']}: {'played ' + game['headline'] if game else 'no game'}"
              f"{' | ' + game['stat'] if game and game['stat'] else ''}")
        if game:
            game.update(id=f"team-{re.sub(r'[^a-z0-9]+', '-', team['name'].lower())}",
                        topic="myteams", why="")
            out.append(game)
    return out


def _broadcasts(comp: dict) -> str:
    """'ESPN' or 'FanDuel SN, KENS' — national networks first."""
    national, local = [], []
    for b in comp.get("broadcasts") or []:
        dest = national if (b.get("market") or "").lower() == "national" else local
        dest.extend(b.get("names") or [])
    for g in comp.get("geoBroadcasts") or []:
        name = ((g.get("media") or {}).get("shortName") or "").strip()
        if name:
            ((national if (g.get("market") or {}).get("type", "").lower() == "national" else local)).append(name)
    names = list(dict.fromkeys(n for n in national + local if n))
    return ", ".join(names[:2])


def todays_game(team: dict, today: datetime, fetch_json, tz) -> dict | None:
    """The team's game later today, if any: who, when (local time) and where to watch."""
    league = team["league"]
    url = (f"https://site.api.espn.com/apis/site/v2/sports/{LEAGUES[league]}/scoreboard"
           f"?dates={today:%Y%m%d}&limit=400")
    if league == "college-football":
        url += "&groups=80"
    elif league == "college-basketball":
        url += "&groups=50"
    data = fetch_json(url)
    if not data:
        return None
    for ev in data.get("events", []):
        comp = (ev.get("competitions") or [{}])[0]
        state = ((comp.get("status") or ev.get("status") or {}).get("type") or {}).get("state", "")
        if state == "post":
            continue
        sides = comp.get("competitors", [])
        mine = next((c for c in sides if _matches(team, c.get("team", {}))), None)
        if not mine or len(sides) != 2:
            continue
        other = next(c for c in sides if c is not mine)
        me = mine["team"].get("shortDisplayName") or mine["team"].get("name") or team["name"]
        opp = other["team"].get("shortDisplayName") or other["team"].get("name") or "Opponent"
        when, start_iso, is_today = "", "", True
        try:
            start = datetime.fromisoformat((ev.get("date") or comp.get("date")).replace("Z", "+00:00")).astimezone(tz)
            when, start_iso = start.strftime("%-I:%M %p"), start.isoformat()
            is_today = start.date() == today.date()
        except (AttributeError, ValueError, TypeError):
            pass
        rec = lambda c: ((c.get("records") or [{}])[0].get("summary") or "")
        return {
            "team": me, "opponent": opp,
            "home": mine.get("homeAway") == "home",
            "matchup": f"{me} {'vs.' if mine.get('homeAway') == 'home' else 'at'} {opp}",
            "time": when, "start": start_iso, "today": is_today, "tv": _broadcasts(comp),
            "record": rec(mine), "opp_record": rec(other),
            "live": state == "in",
        }
    return None


LOOKAHEAD_DAYS = 21


def upcoming_games(teams_file: Path, today_local: datetime, helpers: dict, tz) -> list[dict]:
    """Each team's next game (today or within three weeks), for quick lookup in the app."""
    out = []
    for team in load_teams(teams_file):
        for d in range(LOOKAHEAD_DAYS):
            day = today_local + timedelta(days=d)
            try:
                g = todays_game(team, day, helpers["fetch_json"], tz)
            except Exception as e:  # noqa: BLE001
                print(f"  ! next game for {team['name']}: {e}", file=sys.stderr)
                break
            if g:
                g["today"] = d == 0 and g.get("today", True)
                print(f"  next: {g['matchup']} {g['start'] or day.date()} {g['tv']}")
                out.append(g)
                break
        else:
            print(f"  next: no {team['name']} game in the next {LOOKAHEAD_DAYS} days")
    return out
