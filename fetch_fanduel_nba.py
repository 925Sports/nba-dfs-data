import requests
import json
import re
from datetime import datetime, timezone

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.fanduel.com",
    "Referer": "https://www.fanduel.com/research/nba/fantasy/dfs-projections"
}

GRAPHQL_URL = "https://fdresearch-api.fanduel.com/graphql"

QUERY = """
query GetProjections($input: ProjectionsInput!) {
  getProjections(input: $input) {
    ... on NbaPlayer {
      player { 
        name 
        position 
        numberFireId
      }
      team { abbreviation }
      minutes
      fantasy
      points
      rebounds
      assists
      steals
      blocks
      turnovers
      salary
      value
    }
  }
}
"""

def clean_number(val):
    if val is None or val == "" or str(val).upper() == "N/A":
        return 0.0
    if isinstance(val, (int, float)):
        return float(val)
    cleaned = str(val).replace("$", "").replace(",", "").strip()
    try:
        return float(cleaned) if cleaned else 0.0
    except ValueError:
        return 0.0

def find_candidate_ids():
    try:
        r = requests.get(
            "https://www.fanduel.com/research/nba/fantasy/dfs-projections",
            headers={"User-Agent": HEADERS["User-Agent"]},
            timeout=15
        )
        candidates = set(re.findall(r'\b(10\d{5,6})\b', r.text))
        sorted_cands = sorted(candidates, reverse=True)
        print(f"Found {len(sorted_cands)} candidate IDs")
        return sorted_cands[:12]
    except Exception as e:
        print(f"Scrape error: {e}")
        return []

def test_slate(slate_id):
    payload = {
        "operationName": "GetProjections",
        "variables": {
            "input": {
                "type": "DAILY",
                "position": "NBA_PLAYER",
                "sport": "NBA",
                "slateId": slate_id
            }
        },
        "query": QUERY
    }
    try:
        r = requests.post(GRAPHQL_URL, json=payload, headers=HEADERS, timeout=20)
        data = r.json()
        projs = data.get("data", {}).get("getProjections") or []
        if projs and projs[0].get("player"):
            print(f"  Player keys: {list(projs[0]['player'].keys())}")
        return projs
    except Exception as e:
        print(f"  Error testing {slate_id}: {e}")
        return []

def collect_all_slates():
    candidates = find_candidate_ids()
    all_players = {}
    kept_slates = []

    for sid in candidates:
        projs = test_slate(sid)
        count = len(projs)
        print(f"  {sid}: {count} players")
        if count < 15:
            continue

        kept_slates.append({"slateId": sid, "count": count})
        for p in projs:
            if not p.get("player") or not p["player"].get("name"):
                continue
            player = p["player"]["name"].strip()
            pos = (p["player"].get("position") or "").split("/")[0].upper()
            team = (p.get("team") or {}).get("abbreviation", "").upper()
            minutes = float(p.get("minutes") or 0)
            fpts = float(p.get("fantasy") or 0)
            if not player or minutes <= 0 or minutes > 48:
                continue

            fd_id = p.get("player", {}).get("numberFireId") or ""

            stats = {
                "min": round(minutes, 2),
                "fpts": round(fpts, 2),
                "pts": round(float(p.get("points") or 0), 2),
                "reb": round(float(p.get("rebounds") or 0), 2),
                "ast": round(float(p.get("assists") or 0), 2),
                "stl": round(float(p.get("steals") or 0), 2),
                "blk": round(float(p.get("blocks") or 0), 2),
                "to": round(float(p.get("turnovers") or 0), 2),
                "salary": clean_number(p.get("salary")),
                "value": round(clean_number(p.get("value")), 2)
            }
            key = player.lower()
            if key not in all_players or stats["min"] > all_players[key]["stats"]["min"]:
                all_players[key] = {
                    "info": {
                        "player": player,
                        "position": pos,
                        "team": team,
                        "opp": "",
                        "slateId": sid,
                        "fdId": str(fd_id) if fd_id else ""
                    },
                    "stats": stats
                }

    return all_players, kept_slates

def main():
    players, kept_slates = collect_all_slates()
    if not players:
        print("No usable slates found")
        return

    output = {
        "updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "slates": kept_slates,
        "playerCount": len(players),
        "players": players
    }
    with open("fanduel_nba_projections.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {len(players)} NBA players from {len(kept_slates)} slates")

if __name__ == "__main__":
    main()
