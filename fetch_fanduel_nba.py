import requests
import json
import re
from datetime import datetime

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

GRAPHQL_URL = "https://fdresearch-api.fanduel.com/graphql"

def get_slate_id():
    try:
        url = "https://www.fanduel.com/research/nba/fantasy/dfs-projections"
        r = requests.get(url, headers=HEADERS, timeout=15)
        html = r.text
        # Common patterns for slateId in FanDuel pages
        patterns = [
            r'slateId["\']?\s*[:=]\s*["\']?(\d{6,8})',
            r'"slateId"\s*:\s*"?(\d+)"?',
            r'slateId=(\d+)',
            r'fixtureListId["\']?\s*[:=]\s*["\']?(\d+)',
            r'"id"\s*:\s*"?(\d{7,8})"?.*main',
        ]
        for pat in patterns:
            m = re.search(pat, html, re.I)
            if m:
                print(f"Found slateId: {m.group(1)}")
                return m.group(1)
    except Exception as e:
        print(f"Slate scrape error: {e}")
    print("Using fallback slateId")
    return "1048244"  # last known; update if needed

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

def fetch_nba(slate_id):
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
    r = requests.post(GRAPHQL_URL, json=payload, headers={
        "User-Agent": HEADERS["User-Agent"],
        "Content-Type": "application/json",
        "Origin": "https://www.fanduel.com",
        "Referer": "https://www.fanduel.com/research/nba/fantasy/dfs-projections"
    }, timeout=25)
    print("Status:", r.status_code)
    print(r.text[:800])
    data = r.json()
    return data.get("data", {}).get("getProjections") or []

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
    slate_id = get_slate_id()
    try:
        projections = fetch_nba(slate_id)
        players = normalize(projections)
        output = {
            "updated": datetime.utcnow().isoformat() + "Z",
            "slateId": slate_id,
            "players": players
        }
        with open("fanduel_nba_projections.json", "w") as f:
            json.dump(output, f, indent=2)
        print(f"Wrote {len(players)} NBA players (slate {slate_id})")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
