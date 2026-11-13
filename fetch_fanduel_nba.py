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
      player { name position }
      team { abbreviation }
      minutes
      fantasy
      points
      rebounds
      assists
      steals
      blocks
      turnovers
    }
  }
}
"""

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
        return sorted_cands[:10]
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
        return data.get("data", {}).get("getProjections") or []
    except Exception as e:
        print(f"  Error testing {slate_id}: {e}")
        return []

def find_best_slate():
    candidates = find_candidate_ids()
    best_id = None
    best_projs = []
    best_count = 0

    for sid in candidates:
        projs = test_slate(sid)
        count = len(projs)
        print(f"  {sid}: {count} players")
        # Prefer larger slates (main slate is usually 100+)
        if count > best_count and count >= 20:
            best_count = count
            best_id = sid
            best_projs = projs
        if best_count >= 120:
            break

    return best_id, best_projs

def normalize(projections):
    result = {}
    for p in projections:
        if not p.get("player") or not p["player"].get("name"):
            continue
        player = p["player"]["name"].strip()
        pos = (p["player"].get("position") or "").split("/")[0].upper()
        team = (p.get("team") or {}).get("abbreviation", "").upper()
        minutes = float(p.get("minutes") or 0)
        fpts = float(p.get("fantasy") or 0)
        if not player or minutes <= 0 or minutes > 48:
            continue
        stats = {
            "min": round(minutes, 2),
            "fpts": round(fpts, 2),
            "pts": round(float(p.get("points") or 0), 2),
            "reb": round(float(p.get("rebounds") or 0), 2),
            "ast": round(float(p.get("assists") or 0), 2),
            "stl": round(float(p.get("steals") or 0), 2),
            "blk": round(float(p.get("blocks") or 0), 2),
            "to": round(float(p.get("turnovers") or 0), 2)
        }
        key = player.lower()
        result[key] = {
            "info": {"player": player, "position": pos, "team": team, "opp": ""},
            "stats": stats
        }
    return result

def main():
    slate_id, projections = find_best_slate()
    if not slate_id or not projections:
        print("No usable slate found")
        return

    players = normalize(projections)
    output = {
        "updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "slateId": slate_id,
        "playerCount": len(players),
        "players": players
    }
    with open("fanduel_nba_projections.json", "w") as f:
        json.dump(output, f, indent=2)
    print(f"Wrote {len(players)} NBA players (slate {slate_id})")

if __name__ == "__main__":
    main()
