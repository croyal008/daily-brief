#!/usr/bin/env python3
"""Add the local weather to today's brief.

Uses Open-Meteo (free, no key). The location comes from docs/config.json ("weather"),
which the app's Settings writes; it defaults to San Antonio. Adds a "weather" block and a
Weather topic to docs/data/latest.json and today's archive copy.

Run after build_brief.py:  python scripts/weather.py
"""
from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "docs" / "data"
CONFIG = ROOT / "docs" / "config.json"
DEFAULT = {"name": "San Antonio, TX", "lat": 29.4241, "lon": -98.4936}
TOPIC = {"id": "weather", "name": "Weather", "emoji": "🌤️", "default_on": True}

# WMO weather codes -> (short description, emoji)
CODES = {
    0: ("Clear", "☀️"), 1: ("Mostly clear", "🌤️"), 2: ("Partly cloudy", "⛅"), 3: ("Cloudy", "☁️"),
    45: ("Foggy", "🌫️"), 48: ("Icy fog", "🌫️"),
    51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌧️"),
    56: ("Freezing drizzle", "🌧️"), 57: ("Freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"), 67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"), 73: ("Snow", "🌨️"), 75: ("Heavy snow", "❄️"), 77: ("Snow grains", "🌨️"),
    80: ("Showers", "🌦️"), 81: ("Showers", "🌧️"), 82: ("Heavy showers", "⛈️"),
    85: ("Snow showers", "🌨️"), 86: ("Snow showers", "❄️"),
    95: ("Thunderstorms", "⛈️"), 96: ("Storms with hail", "⛈️"), 99: ("Storms with hail", "⛈️"),
}
SLOTS = [("Morning", 8), ("Midday", 12), ("Afternoon", 16), ("Evening", 20)]


def code(c) -> tuple[str, str]:
    return CODES.get(int(c or 0), ("Mixed", "🌡️"))


def location() -> dict:
    try:
        w = json.loads(CONFIG.read_text()).get("weather") or {}
        if "lat" in w and "lon" in w:
            return {"name": w.get("name") or DEFAULT["name"], "lat": float(w["lat"]), "lon": float(w["lon"])}
    except (OSError, ValueError, TypeError):
        pass
    return DEFAULT


def forecast(loc: dict) -> dict:
    q = urllib.parse.urlencode({
        "latitude": loc["lat"], "longitude": loc["lon"], "timezone": "auto", "forecast_days": 8,
        "temperature_unit": "fahrenheit", "wind_speed_unit": "mph", "precipitation_unit": "inch",
        "daily": ",".join([
            "weather_code", "temperature_2m_max", "temperature_2m_min", "apparent_temperature_max",
            "apparent_temperature_min", "precipitation_probability_max", "precipitation_sum",
            "wind_speed_10m_max", "wind_gusts_10m_max", "uv_index_max", "sunrise", "sunset"]),
        "hourly": "temperature_2m,precipitation_probability,weather_code",
    })
    req = urllib.request.Request(f"https://api.open-meteo.com/v1/forecast?{q}",
                                 headers={"User-Agent": "daily-brief/1.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)


def clock(iso: str) -> str:
    return datetime.fromisoformat(iso).strftime("%-I:%M %p")


def build(loc: dict, f: dict) -> dict:
    d, h = f["daily"], f["hourly"]
    today = d["time"][0]
    hi, lo = round(d["temperature_2m_max"][0]), round(d["temperature_2m_min"][0])
    rain = int(d["precipitation_probability_max"][0] or 0)
    desc, emoji = code(d["weather_code"][0])

    hours = {t: i for i, t in enumerate(h["time"])}
    slots = []
    for label, hr in SLOTS:
        i = hours.get(f"{today}T{hr:02d}:00")
        if i is None:
            continue
        c_desc, c_emoji = code(h["weather_code"][i])
        if hr >= 19 and int(h["weather_code"][i] or 0) in (0, 1):
            c_emoji = "🌙"
        slots.append({"label": label, "temp": round(h["temperature_2m"][i]), "emoji": c_emoji,
                      "desc": c_desc, "rain": int(h["precipitation_probability"][i] or 0)})

    # One or two plain sentences, like a forecaster would say it.
    parts = [f"{desc} today, with a high of {hi}° and a low of {lo}°."]
    if rain >= 30 and slots:
        wettest = max(slots, key=lambda s: s["rain"])
        when = wettest["label"].lower().replace("midday", "around midday")
        when = when if when.startswith("around") else f"in the {when}"
        parts.append(f"{'Rain is likely' if rain >= 60 else 'Some chance of rain'} ({rain}%), most likely {when}.")
    elif rain >= 10:
        parts.append(f"Only a {rain}% chance of rain.")
    else:
        parts.append("No rain expected.")
    wind, gust = round(d["wind_speed_10m_max"][0] or 0), round(d["wind_gusts_10m_max"][0] or 0)
    if gust >= 30:
        parts.append(f"Windy, with gusts up to {gust} mph.")
    elif wind >= 15:
        parts.append(f"Breezy, with winds up to {wind} mph.")
    if hi - lo >= 25:
        parts.append("Big swing from morning to afternoon, so dress in layers.")
    uv = round(d["uv_index_max"][0] or 0)
    if uv >= 8:
        parts.append("The sun is strong today, so wear sunscreen if you're out midday.")

    days = []
    for i in range(1, min(8, len(d["time"]))):
        c_desc, c_emoji = code(d["weather_code"][i])
        days.append({"date": d["time"][i], "emoji": c_emoji, "desc": c_desc,
                     "high": round(d["temperature_2m_max"][i]), "low": round(d["temperature_2m_min"][i]),
                     "rain": int(d["precipitation_probability_max"][i] or 0)})

    return {
        "location": loc["name"],
        "today": {
            "date": today, "emoji": emoji, "desc": desc, "summary": " ".join(parts),
            "high": hi, "low": lo, "rain": rain,
            "feels_high": round(d["apparent_temperature_max"][0]), "feels_low": round(d["apparent_temperature_min"][0]),
            "precip_in": round(d["precipitation_sum"][0] or 0, 2),
            "wind": wind, "gust": gust, "uv": uv,
            "sunrise": clock(d["sunrise"][0]), "sunset": clock(d["sunset"][0]),
            "slots": slots,
        },
        "days": days,
    }


def main() -> int:
    latest = DATA / "latest.json"
    brief = json.loads(latest.read_text())
    loc = location()
    try:
        weather = build(loc, forecast(loc))
    except Exception as e:  # noqa: BLE001  the brief still goes out without weather
        print(f"! Weather skipped: {e}", file=sys.stderr)
        return 0
    brief["weather"] = weather
    brief["topics"] = [TOPIC] + [t for t in brief["topics"] if t["id"] != "weather"]
    payload = json.dumps(brief, ensure_ascii=False, indent=1)
    latest.write_text(payload)
    archive = DATA / "archive" / f"{brief['date']}.json"
    if archive.parent.exists():
        archive.write_text(payload)
    t = weather["today"]
    print(f"Weather for {weather['location']}: {t['desc']}, {t['high']}/{t['low']}, rain {t['rain']}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
