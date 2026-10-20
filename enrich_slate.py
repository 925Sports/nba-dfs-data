#!/usr/bin/env python3
"""Fill Projected FP, Projected Minutes, Ownership, and injury notes.

Run after nba_stats.csv is downloaded. Uses nba_game_log.csv, players.csv,
and drafttable.csv already in the repo, plus ESPN's public injury JSON.
Does not scrape paid sites. Projected FP is the base number, never 1.5x.
"""

import csv
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
STATS = ROOT / "nba_stats.csv"
LOG = ROOT / "nba_game_log.csv"
PLAYERS = ROOT / "players.csv"
DRAFT = ROOT / "drafttable.csv"
ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/injuries"

def norm(name):
    s = unicodedata.normalize("NFKD", str(name or ""))
    s = s.encode("ascii", "ignore").decode()
    s = s.lower().replace(".", " ").replace("'", "").replace("-", " ")
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()

def num(v):
    try:
        return float(str(v).replace("%", "").replace(",", "").strip() or 0)
    except ValueError:
        return 0.0

def read_rows(path):
    with path.open(newline="", encoding="utf-8-sig") as f:
        rows = list(csv.reader(f))
    if not rows:
        raise SystemExit(f"{path.name} is empty")
    return rows[0], rows[1:]

def col(header, name):
    try:
        return header.index(name)
    except ValueError:
        return -1

def ensure(header, name):
    i = col(header, name)
    if i >= 0:
        return i
    header.append(name)
    return len(header) - 1

def dk_points(r, idx):
    pts, reb, ast = num(r[idx["PTS"]]), num(r[idx["REB"]]), num(r[idx["AST"]])
    stl, blk, tov = num(r[idx["STL"]]), num(r[idx["BLK"]]), num(r[idx["TOV"]])
    threes = num(r[idx["3sPM"]])
    fp = pts + 0.5 * threes + 1.25 * reb + 1.5 * ast + 2 * stl + 2 * blk - 0.5 * tov
    cats = sum(1 for x in (pts, reb, ast, stl, blk) if x >= 10)
    if cats >= 3:
        fp += 3
    elif cats >= 2:
        fp += 1.5
    return fp

def load_log():
    header, rows = read_rows(LOG)
    idx = {name: header.index(name) for name in
           ("PLAYER", "GAME DATE", "MIN", "PTS", "REB", "AST", "STL", "BLK", "TOV", "3sPM")}
    by = defaultdict(list)
    for r in rows:
        if len(r) < len(header):
            r = r + [""] * (len(header) - len(r))
        minutes = num(r[idx["MIN"]])
        if minutes <= 0:
            continue
        try:
            when = datetime.strptime(r[idx["GAME DATE"]].strip(), "%m/%d/%Y")
        except ValueError:
            continue
        by[norm(r[idx["PLAYER"]])].append((when, minutes, dk_points(r, idx)))
    out = {}
    for name, games in by.items():
        games.sort(key=lambda g: g[0], reverse=True)
        recent = games[:8]
        if len(recent) < 3:
            continue
        mins = sorted(g[1] for g in recent)
        med = mins[len(mins) // 2]
        rate = sum(g[2] for g in recent) / sum(g[1] for g in recent)
        out[name] = {"minutes": med, "rate": rate}
    return out

def load_meta():
    """Draftable ID -> position, slate, salary, DK status."""
    meta = {}
    if PLAYERS.exists():
        header, rows = read_rows(PLAYERS)
        i_id, i_pos, i_slate, i_sal = (col(header, n) for n in
                                       ("Draftable ID", "Position", "Slate", "Salary"))
        for r in rows:
            if i_id < 0 or i_id >= len(r) or not r[i_id]:
                continue
            meta[r[i_id]] = {
                "pos": r[i_pos] if i_pos >= 0 and i_pos < len(r) else "",
                "slate": r[i_slate] if i_slate >= 0 and i_slate < len(r) else "",
                "salary": num(r[i_sal]) if i_sal >= 0 and i_sal < len(r) else 0,
                "status": "",
            }
    if DRAFT.exists():
        header, rows = read_rows(DRAFT)
        i_id, i_status = col(header, "Draftable ID"), col(header, "Status")
        for r in rows:
            if i_id < 0 or i_id >= len(r) or r[i_id] not in meta:
                continue
            if i_status >= 0 and i_status < len(r):
                meta[r[i_id]]["status"] = (r[i_status] or "").strip().upper()
    return meta

def load_espn():
    try:
        req = Request(ESPN, headers={"User-Agent": "925Sports-nba-enrich"})
        with urlopen(req, timeout=30) as res:
            data = json.loads(res.read().decode())
    except Exception as exc:
        print(f"ESPN injury feed skipped: {exc}")
        return {}
    out = {}
    for team in data.get("injuries", data.get("teams", [])):
        for item in team.get("injuries", []):
            athlete = item.get("athlete") or {}
            name = athlete.get("displayName") or ""
            status = ((item.get("status") or "") if isinstance(item.get("status"), str)
                      else (item.get("status") or {}).get("name") or "")
            details = item.get("details") or {}
            note = (item.get("shortComment") or details.get("shortComment")
                    or details.get("detail") or "")
            if isinstance(note, dict):
                note = note.get("shortComment") or note.get("detail") or ""
            if name:
                out[norm(name)] = {"status": status, "note": str(note)[:180]}
    return out

def is_out(status):
    u = (status or "").upper()
    return u == "OUT" or u == "O" or "OUT" in u

def env_multiplier(ou):
    if ou <= 0:
        return 1.0
    return min(1.08, max(0.92, ou / 226.0))

def main():
    header, rows = read_rows(STATS)
    width = len(header)
    log = load_log()
    meta = load_meta()
    espn = load_espn()

    i_name = col(header, "Player Name")
    i_id = col(header, "Draftable ID")
    i_dk = col(header, "DraftKings")
    i_proj = col(header, "Projected FP")
    i_ou = col(header, "O/U")
    i_imp = col(header, "Implied FP")
    i_inj = col(header, "Injury Status")
    i_note = col(header, "Comment")
    i_min = ensure(header, "Projected Minutes")
    i_own = ensure(header, "Ownership")
    if i_name < 0 or i_proj < 0:
        raise SystemExit("nba_stats.csv is missing Player Name or Projected FP")

    # Base projection by player name. A real DraftKings number wins.
    # The game-log model only fills names that do not have one.
    base = {}
    minutes = {}
    ou_by = defaultdict(list)
    for r in rows:
        r += [""] * (len(header) - len(r))
        name = norm(r[i_name])
        if not name:
            continue
        dk = num(r[i_dk]) if i_dk >= 0 else 0
        if dk > 0:
            base[name] = max(base.get(name, 0), dk)
        if i_ou >= 0:
            ou = num(r[i_ou])
            if ou > 0:
                ou_by[name].append(ou)
        if name in log:
            minutes[name] = log[name]["minutes"]

    for name, model in log.items():
        if base.get(name, 0) > 0:
            continue
        ous = ou_by.get(name) or []
        ou = sorted(ous)[len(ous) // 2] if ous else 0
        base[name] = round(model["rate"] * model["minutes"] * env_multiplier(ou), 2)

    enriched = []
    groups = defaultdict(list)  # (slate, pool) -> [(row_index, score)]
    for n, r in enumerate(rows):
        r += [""] * (len(header) - len(r))
        name = norm(r[i_name])
        did = r[i_id] if i_id >= 0 else ""
        info = meta.get(did, {})
        pos = (info.get("pos") or "").upper()
        status = (info.get("status") or "").upper()
        espn_row = espn.get(name, {})
        out = is_out(status) or is_out(espn_row.get("status", ""))

        proj = 0.0 if out else base.get(name, 0.0)
        mins = 0.0 if out else minutes.get(name, 0.0)
        if i_proj >= 0:
            r[i_proj] = f"{proj:.2f}" if proj > 0 else ""
        if i_imp >= 0:
            r[i_imp] = r[i_proj]
        r[i_min] = f"{mins:.1f}" if mins > 0 else ""

        if espn:
            if i_note >= 0:
                r[i_note] = "" if out and not espn_row else (espn_row.get("note") or "")
            if i_inj >= 0:
                if status in ("OUT", "O", "Q"):
                    r[i_inj] = "Out" if status in ("OUT", "O") else "Q"
                elif is_out(espn_row.get("status", "")):
                    r[i_inj] = "Out"
                elif "DAY" in (espn_row.get("status") or "").upper():
                    r[i_inj] = "Questionable"
                else:
                    r[i_inj] = ""

        slate = info.get("slate") or "slate"
        pool = "CPT" if pos == "CPT" else "roster"
        slots = 1 if pool == "CPT" else (5 if "showdown" in slate.lower() else 8)
        salary = info.get("salary") or num(r[col(header, "Salary")]) if col(header, "Salary") >= 0 else 0
        base_salary = salary / 1.5 if pos == "CPT" and salary else salary
        if proj > 0 and base_salary > 0:
            value = proj / (base_salary / 1000.0)
            score = (proj ** 1.1) * (value ** 0.35) * (((mins or 24) / 32) ** 0.25)
            groups[(slate, pool, slots)].append((n, score))
        else:
            r[i_own] = ""
        enriched.append(r)

    for (slate, pool, slots), items in groups.items():
        total = sum(score for _, score in items) or 1
        cap = 45 if pool == "CPT" else 55
        for n, score in items:
            own = min(cap, 100.0 * score / total * slots)
            enriched[n][i_own] = f"{own:.1f}"

    with STATS.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(enriched)
    filled = sum(1 for r in enriched if num(r[i_proj]) > 0)
    print(f"Wrote {STATS.name}: {filled} rows with a projection, ownership by slate.")

if __name__ == "__main__":
    main()
