#!/usr/bin/env python3
"""Write projected_starters.csv from the public RotoWire expected lineups.

This is the expected five, not the ESPN depth chart. A player who is out
is already replaced here. Run it from the nba-dfs-data repo. It overwrites
projected_starters.csv.

The page markup can change. If it does, the script exits without writing
so a bad run cannot wipe a good file.
"""
import csv
import re
import urllib.request

URL = "https://www.rotowire.com/basketball/nba-lineups.php"
OUT = "projected_starters.csv"
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; 925Sports/1.0)"}
FIELDS = ["Team", "Position", "Player Name", "Source"]

# RotoWire short codes to the DraftKings codes the builder uses.
ALIAS = {
    "SA": "SAS", "SAN": "SAS",
    "GS": "GSW", "GOS": "GSW",
    "NY": "NYK",
    "NO": "NOP", "NOR": "NOP",
    "WSH": "WAS",
    "UTAH": "UTA",
    "PHO": "PHX",
    "CHO": "CHA",
    "BRK": "BKN", "BK": "BKN",
}
SLOTS = {"PG", "SG", "SF", "PF", "C"}


def canon(team):
    text = (team or "").strip().upper()
    return ALIAS.get(text, text)


def main():
    req = urllib.request.Request(URL, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=40) as res:
        html = res.read().decode("utf-8", "replace")

    rows = []
    seen = set()
    for part in re.split(r'class="lineup is-nba"', html)[1:]:
        teams = re.findall(r'class="lineup__abbr">([A-Z]{2,4})', part)
        lists = re.findall(r'lineup__list is-(visit|home)">([\s\S]*?)</ul>', part)
        for side, block in lists:
            players = re.findall(
                r'lineup__pos"\s*>([A-Z]{1,3})</div>\s*<a title="([^"]+)"',
                block,
            )
            idx = 0 if side == "visit" else 1
            if idx >= len(teams) or len(players) < 5:
                continue
            team = canon(teams[idx])
            if not team or team in seen:
                continue
            five = [(pos, name.strip()) for pos, name in players[:5] if pos in SLOTS and name.strip()]
            if len(five) < 5:
                continue
            seen.add(team)
            for pos, name in five:
                rows.append({
                    "Team": team,
                    "Position": pos,
                    "Player Name": name,
                    "Source": "RotoWire",
                })
            print(team, [name for _, name in five])

    # A full slate is 8 to 15 games. Refuse to overwrite on a short or empty parse.
    if len(rows) < 40:
        raise SystemExit(f"Only {len(rows)} starter rows. Not overwriting.")

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows for {len(seen)} teams to {OUT}")


if __name__ == "__main__":
    main()
