#!/usr/bin/env python3
"""
NBA DraftKings salary pipeline.
Fetches Classic and Showdown Captain Mode slates only.
Uses public salary CSV (draftables JSON 403s from GitHub Actions).
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlparse

import requests

LOBBY_URL = "https://www.draftkings.com/lobby/getcontests?sport=NBA"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Referer": "https://www.draftkings.com/lobby#/NBA",
    "Origin": "https://www.draftkings.com",
    "Accept": "application/json, text/plain, */*",
}

# Keep only these GameTypeIds (confirmed from lobby)
KEEP_GAME_TYPE_IDS = {70: "Classic", 81: "Showdown Captain Mode"}

SKIP_KEYWORDS = re.compile(
    r"best.?ball|snake|tiers|single.?stat|in.?game|stat.?only|qualifier|satellite",
    re.I,
)

def fetch_lobby():
    r = requests.get(LOBBY_URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.json()

def parse_game_info(game_info):
    """Parse 'OKC@SAS 10/20/2026 09:30PM ET' into components."""
    if not game_info:
        return "", "", "", ""
    parts = game_info.strip().split()
    matchup = parts[0] if parts else ""
    date_str = ""
    time_str = ""
    for p in parts[1:]:
        if re.match(r"\d{2}/\d{2}/\d{4}", p):
            date_str = p
        elif re.match(r"\d{1,2}:\d{2}[AP]M", p, re.I):
            time_str = p
    start = f"{date_str} {time_str}".strip()
    return matchup, date_str, time_str, start

def get_opponent(team, matchup):
    if not matchup or "@" not in matchup:
        return ""
    away, home = matchup.split("@")
    team = team.upper()
    if team == away.upper():
        return home.upper()
    if team == home.upper():
        return away.upper()
    return ""

def fetch_csv(dg_id):
    url = f"https://www.draftkings.com/lineup/getavailableplayerscsv?draftGroupId={dg_id}"
    r = requests.get(url, headers=HEADERS, timeout=30)
    if r.status_code != 200 or "Name" not in r.text[:300]:
        return None
    text = r.text.lstrip("\ufeff")
    reader = csv.DictReader(text.splitlines())
    rows = list(reader)
    return rows if rows else None

def build_role(slate_type, start_str, game_count, matchup):
    """Role is the slate label.
    Classic: Classic 10/18 7:00PM, 6 Games
    Showdown: Showdown Captain Mode LAL@BOS 10/18 7:30PM
    """
    # Normalize time display (drop leading zero on hour if present, keep ET implied)
    display_time = start_str
    if display_time:
        # Convert 09:30PM -> 9:30PM for readability
        display_time = re.sub(r"^0(\d:)", r"\1", display_time)
    date_part = ""
    time_part = ""
    m = re.search(r"(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2}[AP]M)", start_str or "", re.I)
    if m:
        date_part = m.group(1)[0:5]  # MM/DD
        time_part = re.sub(r"^0(\d:)", r"\1", m.group(2))

    if slate_type == "Classic":
        return f"Classic {date_part} {time_part}, {game_count} Games".strip()
    else:
        return f"Showdown Captain Mode {matchup} {date_part} {time_part}".strip()

def main():
    print("Fetching NBA lobby...")
    data = fetch_lobby()
    contests = data.get("Contests", [])
    draft_groups = {dg["DraftGroupId"]: dg for dg in data.get("DraftGroups", [])}

    # On every run print GameTypeIds (user asked for first run, but useful always)
    print("\n=== GameTypeId / Contest Name (sample) ===")
    seen = set()
    for c in contests:
        gtid = c.get("gameTypeId")
        name = (c.get("n") or "")[:80]
        key = (gtid, name)
        if key not in seen:
            print(f"  {gtid}: {name}")
            seen.add(key)
            if len(seen) > 40:  # keep log reasonable
                break
    print("==========================================\n")

    # Group contests by draft group, keep only Classic / Showdown Captain Mode
    groups = defaultdict(lambda: {
        "contest_ids": [],
        "contest_names": [],
        "game_type_id": None,
        "slate_type": None,
        "meta": None,
    })

    for c in contests:
        gtid = c.get("gameTypeId")
        name = c.get("n") or ""
        if SKIP_KEYWORDS.search(name):
            continue
        if gtid not in KEEP_GAME_TYPE_IDS:
            continue
        dg_id = c.get("dg")
        if not dg_id:
            continue
        g = groups[dg_id]
        g["contest_ids"].append(str(c.get("id", "")))
        g["contest_names"].append(name)
        g["game_type_id"] = gtid
        g["slate_type"] = KEEP_GAME_TYPE_IDS[gtid]
        if dg_id in draft_groups:
            g["meta"] = draft_groups[dg_id]

    if not groups:
        print("No Classic or Showdown Captain Mode contests found.")
        sys.exit(1)

    all_drafttable = []
    all_players = []
    total_players = 0

    for dg_id, info in sorted(groups.items()):
        meta = info["meta"] or {}
        slate_type = info["slate_type"]
        game_count = meta.get("GameCount", 1)
        print(f"Fetching CSV for dg={dg_id} ({slate_type}, {game_count} games)...")

        rows = fetch_csv(dg_id)
        if not rows:
            print(f"  CSV returned 0 player rows for {dg_id}. Skipping overwrite.")
            # Do not overwrite; continue so other slates can succeed, but track failure
            continue

        # Determine start time / matchup from first player or meta
        sample_game = rows[0].get("Game Info", "")
        matchup, date_str, time_str, start_raw = parse_game_info(sample_game)
        role = build_role(slate_type, start_raw, game_count, matchup)

        contest_ids_short = ";".join(info["contest_ids"][:20])
        contest_ids_full = ";".join(info["contest_ids"])
        contest_names_short = ";".join(info["contest_names"][:10])

        for row in rows:
            name = (row.get("Name") or "").strip()
            if not name:
                continue
            salary = int(float(row.get("Salary") or 0))
            if salary <= 0:
                continue
            draftable_id = str(row.get("ID") or "").strip()
            position = (row.get("Position") or "").upper()
            roster = (row.get("Roster Position") or "").upper()
            team = (row.get("TeamAbbrev") or "").upper()
            game_info = row.get("Game Info", "")
            status = (row.get("Status") or "").strip()
            image = ""  # CSV does not provide image URL

            matchup_p, _, _, start_p = parse_game_info(game_info)
            opponent = get_opponent(team, matchup_p)
            game = matchup_p.replace("@", " @ ") if matchup_p else ""
            start_time = start_p

            # Player ID style
            player_id = f"{name}|{team}"

            # Split name
            name_parts = name.split()
            first = name_parts[0] if name_parts else ""
            last = " ".join(name_parts[1:]) if len(name_parts) > 1 else ""

            # For Showdown, Roster Position is CPT or UTIL
            pos_out = roster if roster in ("CPT", "UTIL") else position
            if slate_type.startswith("Showdown") and roster == "CPT":
                pos_out = "CPT"
            elif slate_type.startswith("Showdown"):
                pos_out = "UTIL"

            player_name_slate = f"{name} - {slate_type}"

            draft_row = [
                player_name_slate,
                contest_ids_short,
                player_id,
                draftable_id,
                name,
                first,
                last,
                salary,
                pos_out,
                team,
                game,
                start_time,
                image,
                game,  # Tournament
                slate_type,
                "NBA",
                date_str[:5] if date_str else "",
                role,  # Role = slate label
                contest_names_short,
                contest_ids_full,
                role,  # Slate Header = same as Role for simplicity
            ]
            all_drafttable.append(draft_row)

            # players.csv row (one per unique player-slate; for Showdown both CPT and UTIL rows exist)
            player_row = [
                name,
                pos_out,
                team,
                opponent,
                role,          # Slate
                slate_type,
                salary,
                draftable_id,
                game,
                start_time,
                image,
            ]
            all_players.append(player_row)
            total_players += 1

        print(f"  Added {len(rows)} rows for {role}")

    if total_players == 0:
        print("ERROR: No player rows collected from any CSV. Not overwriting existing files.")
        sys.exit(1)

    # Write drafttable.csv
    draft_headers = [
        "Player Name - Slate Type", "Contest IDs", "Player ID", "Draftable ID",
        "Player Name", "First Name", "Last Name", "Salary", "Position", "Team",
        "Game", "Game Start Time", "Player Image", "Tournament", "Slate Type",
        "Game Type", "Date", "Role", "Contest Names", "Contest IDs (Full)", "Slate Header"
    ]
    with open("drafttable.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(draft_headers)
        w.writerows(all_drafttable)
    print(f"Wrote {len(all_drafttable)} rows to drafttable.csv")

    # Write players.csv
    player_headers = [
        "Player Name", "Position", "Team", "Opponent", "Slate", "Slate Type",
        "Salary", "Draftable ID", "Game", "Game Start Time", "Player Image"
    ]
    with open("players.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(player_headers)
        w.writerows(all_players)
    print(f"Wrote {len(all_players)} rows to players.csv")

    print("Done.")

if __name__ == "__main__":
    main()
