#!/usr/bin/env python3
"""Append 2026-27 NBA game logs from ESPN box scores.

The GitHub workflow currently downloads a Google Sheet that still ends in
June 2026. Run this instead, or after that download, so 2026-27 games land
in nba_game_log.csv.

Usage:
  python fetch_game_log.py
  python fetch_game_log.py --start 2026-10-20 --end 2026-10-23
"""
import argparse
import csv
import json
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0"}
OUT = Path("nba_game_log.csv")
FIELDS = [
    "PLAYER", "TEAM", "MATCH UP", "GAME DATE", "W/L", "MIN", "PTS",
    "FGM", "FGA", "FG%", "3sPM", "3PA", "3P%", "FTM", "FTA", "FT%",
    "OREB", "DREB", "REB", "AST", "STL", "BLK", "TOV", "PF", "Plus/Minus", "FP",
]


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=40) as r:
        return json.load(r)


def split_made(cell):
    text = str(cell or "0-0")
    if "-" not in text:
        return 0, 0, ""
    made, att = text.split("-", 1)
    try:
        m, a = int(made), int(att)
    except ValueError:
        return 0, 0, ""
    pct = "" if a == 0 else f"{round(100 * m / a, 1)}"
    return m, a, pct


def dk_fp(pts, fg3m, reb, ast, stl, blk, tov):
    tens = sum(1 for n in (pts, reb, ast, stl, blk) if n >= 10)
    bonus = 3 if tens >= 3 else 1.5 if tens >= 2 else 0
    return round(pts + 0.5 * fg3m + 1.25 * reb + 1.5 * ast + 2 * stl + 2 * blk - 0.5 * tov + bonus, 1)


def games_on(day):
    data = get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates={day:%Y%m%d}")
    out = []
    for event in data.get("events", []):
        comp = (event.get("competitions") or [{}])[0]
        teams = comp.get("competitors") or []
        if len(teams) < 2 or not comp.get("status", {}).get("type", {}).get("completed"):
            continue
        by_ha = {t.get("homeAway"): t for t in teams}
        home, away = by_ha.get("home"), by_ha.get("away")
        if not home or not away:
            continue
        out.append({
            "id": event["id"],
            "date": f"{day.month}/{day.day}/{day.year}",
            "home": home["team"]["abbreviation"],
            "away": away["team"]["abbreviation"],
            "home_score": int(home.get("score") or 0),
            "away_score": int(away.get("score") or 0),
        })
    return out


def rows_for(game):
    data = get(f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event={game['id']}")
    rows = []
    for side in data.get("boxscore", {}).get("players", []):
        team = side.get("team", {}).get("abbreviation", "")
        opp = game["away"] if team == game["home"] else game["home"]
        loc = "vs." if team == game["home"] else "@"
        won = (team == game["home"] and game["home_score"] > game["away_score"]) or (
            team == game["away"] and game["away_score"] > game["home_score"]
        )
        stats = (side.get("statistics") or [{}])[0]
        labels = stats.get("labels") or []
        idx = {label: i for i, label in enumerate(labels)}
        for athlete in stats.get("athletes", []):
            name = (athlete.get("athlete") or {}).get("displayName", "")
            cells = athlete.get("stats") or []
            if not name or not cells or athlete.get("didNotPlay"):
                continue
            def cell(label):
                i = idx.get(label)
                return cells[i] if i is not None and i < len(cells) else ""
            try:
                mins = int(str(cell("MIN")).split(":")[0] or 0)
            except ValueError:
                mins = 0
            if mins <= 0:
                continue
            fgm, fga, fg = split_made(cell("FG"))
            fg3m, fg3a, fg3 = split_made(cell("3PT"))
            ftm, fta, ft = split_made(cell("FT"))
            pts, reb, ast = int(cell("PTS") or 0), int(cell("REB") or 0), int(cell("AST") or 0)
            stl, blk, tov = int(cell("STL") or 0), int(cell("BLK") or 0), int(cell("TO") or 0)
            rows.append({
                "PLAYER": name,
                "TEAM": team,
                "MATCH UP": f"{team} {loc} {opp}",
                "GAME DATE": game["date"],
                "W/L": "W" if won else "L",
                "MIN": mins,
                "PTS": pts,
                "FGM": fgm,
                "FGA": fga,
                "FG%": fg,
                "3sPM": fg3m,
                "3PA": fg3a,
                "3P%": fg3,
                "FTM": ftm,
                "FTA": fta,
                "FT%": ft,
                "OREB": int(cell("OREB") or 0),
                "DREB": int(cell("DREB") or 0),
                "REB": reb,
                "AST": ast,
                "STL": stl,
                "BLK": blk,
                "TOV": tov,
                "PF": int(cell("PF") or 0),
                "Plus/Minus": cell("+/-"),
                "FP": dk_fp(pts, fg3m, reb, ast, stl, blk, tov),
            })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2026-10-20")
    parser.add_argument("--end", default=date.today().isoformat())
    args = parser.parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    existing = []
    seen = set()
    if OUT.exists():
        with OUT.open(newline="", encoding="utf-8") as f:
            existing = list(csv.DictReader(f))
        for row in existing:
            seen.add((row.get("PLAYER"), row.get("GAME DATE"), row.get("TEAM")))
    added = []
    day = start
    while day <= end:
        try:
            games = games_on(day)
        except Exception as exc:
            print(f"{day} scoreboard failed: {exc}")
            day += timedelta(days=1)
            continue
        print(f"{day} {len(games)} final games")
        for game in games:
            try:
                for row in rows_for(game):
                    key = (row["PLAYER"], row["GAME DATE"], row["TEAM"])
                    if key in seen:
                        continue
                    seen.add(key)
                    added.append(row)
            except Exception as exc:
                print(f"  {game['id']} failed: {exc}")
            time.sleep(0.3)
        day += timedelta(days=1)
    with OUT.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(existing)
        writer.writerows(added)
    print(f"Kept {len(existing)} old rows, added {len(added)} 2026-27 rows.")


if __name__ == "__main__":
    main()
