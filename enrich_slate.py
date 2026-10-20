#!/usr/bin/env python3
"""Keep the sheet's projection. Do not invent one.

Run after nba_stats.csv is downloaded. Projected FP is copied from the
sheet. A blank or 0 stays blank. There is no game-log fill.

Projected Minutes is MIN Avg from the sheet, and blank when that is 0.
Ownership is written only for players who have a projection.
Injury notes still come from the DraftKings status and ESPN's public feed.
"""

import csv
import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
STATS = ROOT / "nba_stats.csv"
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


def main():
    header, rows = read_rows(STATS)
    meta = load_meta()
    espn = load_espn()

    i_name = col(header, "Player Name")
    i_id = col(header, "Draftable ID")
    i_proj = col(header, "Projected FP")
    i_min_avg = col(header, "MIN Avg")
    i_inj = col(header, "Injury Status")
    i_note = col(header, "Comment")
    i_min = ensure(header, "Projected Minutes")
    i_own = ensure(header, "Ownership")
    i_sal = col(header, "Salary")
    i_pos = col(header, "Position")
    i_slate = col(header, "Slate Type")
    if i_name < 0 or i_proj < 0:
        raise SystemExit("nba_stats.csv is missing Player Name or Projected FP")

    enriched = []
    groups = defaultdict(list)
    kept = 0
    for n, r in enumerate(rows):
        r += [""] * (len(header) - len(r))
        name = norm(r[i_name])
        did = r[i_id] if i_id >= 0 else ""
        info = meta.get(did, {})
        pos = (info.get("pos") or (r[i_pos] if i_pos >= 0 else "")).upper()
        status = (info.get("status") or "").upper()
        espn_row = espn.get(name, {})
        out = is_out(status) or is_out(espn_row.get("status", ""))

        proj = 0.0 if out else num(r[i_proj])
        mins = 0.0 if out else (num(r[i_min_avg]) if i_min_avg >= 0 else 0.0)
        if proj > 0:
            r[i_proj] = f"{proj:.2f}"
            kept += 1
        else:
            r[i_proj] = ""
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

        slate = info.get("slate") or (r[i_slate] if i_slate >= 0 else "") or "slate"
        pool = "CPT" if pos == "CPT" else "roster"
        slots = 1 if pool == "CPT" else (5 if "showdown" in slate.lower() else 8)
        salary = info.get("salary") or 0
        if not salary and i_sal >= 0:
            salary = num(r[i_sal])
        base_salary = salary / 1.5 if pos == "CPT" and salary else salary
        if proj > 0 and base_salary > 0:
            value = proj / (base_salary / 1000.0)
            minute_factor = (mins / 32) ** 0.25 if mins > 0 else 1.0
            score = (proj ** 1.1) * (value ** 0.35) * minute_factor
            groups[(slate, pool, slots)].append((n, score))
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
    owned = sum(1 for r in enriched if num(r[i_own]) > 0)
    print(f"Wrote {STATS.name}: {kept} projections kept, {len(enriched) - kept} left blank, {owned} with ownership.")


if __name__ == "__main__":
    main()
