import requests
import json
from datetime import datetime, timedelta

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

def fetch_for_date(date_str):
    """date_str format: YYYY-MM-DD"""
    payload = {
        "operationName": "GetProjections",
        "variables": {
            "input": {
                "type": "DAILY",
                "position": "NBA_PLAYER",
                "sport": "NBA",
                "date": date_str
            }
        },
        "query": QUERY
    }
    r = requests.post(GRAPHQL_URL, json=payload, headers=HEADERS, timeout=25)
    r.raise_for_status()
    data = r.json()
    return data.get("data", {}).get("getProjections", [])

def normalize(projections, date_label):
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
        key = f"{player.lower()}_{date_label}"
        result[key] = {
            "info": {
                "player": player,
                "position": pos,
                "team": team,
                "opp": "",
                "date": date_label
            },
            "stats": stats
        }
    return result

def main():
    today = datetime.utcnow().date()
    tomorrow = today + timedelta(days=1)

    all_players = {}

    for label, dt in [("today", today), ("tomorrow", tomorrow)]:
        date_str = dt.isoformat()
        try:
            projections = fetch_for_date(date_str)
            parsed = normalize(projections, label)
            all_players.update(parsed)
            print(f"{label} ({date_str}): {len(parsed)} players")
        except Exception as e:
            print(f"Error on {label}: {e}")

    output = {
        "updated": datetime.utcnow().isoformat() + "Z",
        "players": all_players
    }

    with open("fanduel_nba_projections.json", "w") as f:
        json.dump(output, f, indent=2)

    print(f"Wrote {len(all_players)} total player-entries")

if __name__ == "__main__":
    main()
