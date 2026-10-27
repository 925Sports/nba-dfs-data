#!/usr/bin/env python3
"""Build nba_dvp.csv from the game log.

Reads nba_game_log.csv, tags each player with a primary position from
Basketball Reference, and writes what every defense has allowed.

Positions:
  PG, SG, SF, PF, C     the player's primary spot
  G                     point guards and shooting guards, added together
  F                     small forwards and power forwards, added together
  C                     centers (same as the C row above)
  GF                    shooting guards and small forwards, added together
  CF                    power forwards and centers, added together

Windows:
  season                every 2026-27 game in the log
  l10                   that defense's last 10 games

Averages in the tool are per team game, not per player. A row's GP is how
many games that defense faced the spot. The other columns are season totals,
and the page divides by GP.

Usage:
  python build_dvp.py
  python build_dvp.py --log nba_game_log.csv --out nba_dvp.csv
"""
import argparse
import csv
import re
import unicodedata
import urllib.request
from collections import defaultdict
from datetime import date
from html import unescape
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0"}
SEASON_START = date(2026, 10, 1)
ALIAS = {
    "NY": "NYK", "NYK": "NYK",
    "SA": "SAS", "SAS": "SAS", "SAN": "SAS",
    "GS": "GSW", "GSW": "GSW", "GOS": "GSW",
    "UTAH": "UTA", "UTA": "UTA",
    "NO": "NOP", "NOR": "NOP", "NOP": "NOP",
    "WSH": "WAS", "WAS": "WAS",
    "PHO": "PHX", "PHX": "PHX",
    "CHO": "CHA", "CHA": "CHA",
    "BRK": "BKN", "BK": "BKN", "BKN": "BKN",
}
PRIMARY = ("PG", "SG", "SF", "PF", "C")
FIELDS = [
    "TEAM", "POS", "WINDOW", "GP", "MIN", "FPTS", "PTS", "OREB", "DREB", "REB",
    "AST", "STL", "BLK", "TOV", "PF", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "PM",
]
STAT_KEYS = ["MIN", "FPTS", "PTS", "OREB", "DREB", "REB", "AST", "STL", "BLK", "TOV", "PF", "FGM", "FGA", "FG3M", "FG3A", "FTM", "FTA", "PM"]


def canon(team):
    team = (team or "").upper().strip()
    return ALIAS.get(team, team)


def fold(name):
    text = unicodedata.normalize("NFD", name or "")
    text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
    text = re.sub(r"\b(jr|sr|ii|iii|iv|v)\b", " ", text, flags=re.I)
    return re.sub(r"[^a-z]", "", text.lower())


def num(value):
    try:
        return float(str(value).replace("%", "") or 0)
    except ValueError:
        return 0.0


def parse_date(value):
    match = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(value or ""))
    if not match:
        return None
    month, day, year = (int(part) for part in match.groups())
    try:
        return date(year, month, day)
    except ValueError:
        return None


def opponent(team, match):
    found = re.search(r"([A-Z]{2,4})\s*(?:@|VS\.?)\s*([A-Z]{2,4})", str(match or "").upper())
    if not found:
        return ""
    left, right = canon(found.group(1)), canon(found.group(2))
    side = canon(team)
    if side == left:
        return right
    if side == right:
        return left
    return ""


def slots_for(pos):
    slots = [pos]
    if pos in ("PG", "SG"):
        slots.append("G")
    if pos in ("SF", "PF"):
        slots.append("F")
    if pos in ("SG", "SF"):
        slots.append("GF")
    if pos in ("PF", "C"):
        slots.append("CF")
    return slots


def cell(row, stat):
    match = re.search(rf'data-stat="{stat}"[^>]*>(.*?)</t[dh]>', row, re.S)
    if not match:
        return ""
    return unescape(re.sub(r"<[^>]+>", "", match.group(1))).strip()


def positions_from_reference():
    url = "https://www.basketball-reference.com/leagues/NBA_2027_per_game.html"
    request = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(request, timeout=40) as response:
        html = response.read().decode("utf-8", "replace").replace("<!--", "").replace("-->", "")
    found = {}
    for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.S):
        name = cell(row, "name_display")
        pos = cell(row, "pos").upper()
        team = cell(row, "team_name_abbr").upper()
        if not name or name == "Player" or pos not in PRIMARY:
            continue
        key = fold(name)
        if team in ("TOT", "2TM"):
            found.setdefault(key, pos)
        else:
            found[key] = pos
    return found


def positions_from_players(path, found):
    file = Path(path)
    if not file.exists():
        return
    with file.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get("Position") or "").upper().split("/")[0].strip()
            if raw not in PRIMARY:
                continue
            key = fold(row.get("Player Name") or "")
            if key and key not in found:
                found[key] = raw


def blank():
    return {key: 0.0 for key in STAT_KEYS}


def add(bucket, row):
    bucket["MIN"] += num(row.get("MIN"))
    bucket["FPTS"] += num(row.get("FP"))
    bucket["PTS"] += num(row.get("PTS"))
    bucket["OREB"] += num(row.get("OREB"))
    bucket["DREB"] += num(row.get("DREB"))
    bucket["REB"] += num(row.get("REB"))
    bucket["AST"] += num(row.get("AST"))
    bucket["STL"] += num(row.get("STL"))
    bucket["BLK"] += num(row.get("BLK"))
    bucket["TOV"] += num(row.get("TOV"))
    bucket["PF"] += num(row.get("PF"))
    bucket["FGM"] += num(row.get("FGM"))
    bucket["FGA"] += num(row.get("FGA"))
    bucket["FG3M"] += num(row.get("3sPM"))
    bucket["FG3A"] += num(row.get("3PA"))
    bucket["FTM"] += num(row.get("FTM"))
    bucket["FTA"] += num(row.get("FTA"))
    bucket["PM"] += num(row.get("Plus/Minus"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--log", default="nba_game_log.csv")
    parser.add_argument("--players", default="players.csv")
    parser.add_argument("--out", default="nba_dvp.csv")
    args = parser.parse_args()
    pos_map = positions_from_reference()
    positions_from_players(args.players, pos_map)
    print(f"Positions for {len(pos_map)} players.")
    if len(pos_map) < 150:
        raise SystemExit("Position list is too short. Basketball Reference did not come through.")

    games = defaultdict(blank)
    team_dates = defaultdict(set)
    used = skipped = 0
    with open(args.log, newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            played = parse_date(row.get("GAME DATE"))
            if not played or played < SEASON_START or num(row.get("MIN")) <= 0:
                continue
            team = canon(row.get("TEAM"))
            defense = opponent(team, row.get("MATCH UP"))
            if team:
                team_dates[team].add(played)
            if defense:
                team_dates[defense].add(played)
            pos = pos_map.get(fold(row.get("PLAYER")))
            if not defense or not pos:
                skipped += 1
                continue
            for slot in slots_for(pos):
                add(games[(defense, slot, played)], row)
            used += 1
    print(f"Used {used} player games, skipped {skipped}.")
    if used < 200:
        raise SystemExit("Not enough 2026-27 games in the log to build DVP.")

    by_slot = defaultdict(list)
    for (defense, slot, played), stats in games.items():
        by_slot[(defense, slot)].append((played, stats))

    rows = []
    for (defense, slot), samples in sorted(by_slot.items()):
        samples.sort(key=lambda item: item[0])
        windows = {"season": samples, "l10": samples[-10:]}
        for window, picked in windows.items():
            total = blank()
            for _, stats in picked:
                for key in STAT_KEYS:
                    total[key] += stats[key]
            out = {
                "TEAM": defense,
                "POS": slot,
                "WINDOW": window,
                "GP": len(picked),
            }
            for key in STAT_KEYS:
                out[key] = round(total[key], 2)
            rows.append(out)

    with open(args.out, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {args.out}.")


if __name__ == "__main__":
    main()
Grok finished responding
