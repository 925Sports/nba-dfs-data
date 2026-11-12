#!/usr/bin/env python3
"""Build teammate on/off splits from ESPN play-by-play.

For each finished game the scoreboard already marks complete, this walks the
play-by-play, keeps the five on the floor, and records two things:

  * How a teammate scores with a player on the floor versus off it.
  * How many minutes that teammate played as the direct sub for him.

The builder uses the sub minutes to move projected minutes when someone is
out, and the on/off rate to scale the projection that those minutes carry.
Double-double and triple-double bonuses are not split across stints.

Outputs, next to this script when you run it from the repo root:
  nba_onoff.csv       one row per player / teammate
  nba_pbp_done.csv    game ids already folded in

Usage:
  python fetch_pbp.py
  python fetch_pbp.py --start 2026-10-20 --end 2026-11-03
  python fetch_pbp.py --rebuild
  python fetch_pbp.py --game 401909903
"""
import argparse
import csv
import json
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

HEADERS = {"User-Agent": "Mozilla/5.0"}
ONOFF = Path("nba_onoff.csv")
DONE = Path("nba_pbp_done.csv")
STAT_KEYS = ["pts", "fg3m", "fga", "fta", "reb", "ast", "stl", "blk", "tov"]
ONOFF_FIELDS = [
    "TEAM", "PLAYER", "TEAMMATE",
    "MIN_ON", "FP_ON", "MIN_OFF", "FP_OFF", "REPL_MIN",
    "PTS_ON", "PTS_OFF", "REB_ON", "REB_OFF", "AST_ON", "AST_OFF",
    "STL_ON", "STL_OFF", "BLK_ON", "BLK_OFF", "TOV_ON", "TOV_OFF",
    "FG3M_ON", "FG3M_OFF", "FGA_ON", "FGA_OFF", "FTA_ON", "FTA_OFF",
    "PLAY_GP", "PLAY_MIN", "MISS_GP", "MISS_MIN",
]
DONE_FIELDS = ["GAME_ID", "DATE", "HOME", "AWAY", "STATUS"]
ALIAS = {
    "NY": "NYK", "SA": "SAS", "SAN": "SAS",
    "GS": "GSW", "GOS": "GSW",
    "UTAH": "UTA", "NO": "NOP", "NOR": "NOP",
    "WSH": "WAS", "PHO": "PHX", "CHO": "CHA",
    "BRK": "BKN", "BK": "BKN",
}


def canon(team):
    text = (team or "").strip().upper()
    return ALIAS.get(text, text)


def get(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=40) as res:
        return json.load(res)


def clock_seconds(display):
    text = str(display or "0:00").strip()
    if ":" not in text:
        try:
            return float(text)
        except ValueError:
            return 0.0
    mins, secs = text.split(":", 1)
    try:
        return int(mins) * 60 + float(secs)
    except ValueError:
        return 0.0


def period_length(period):
    return 5 * 60 if period > 4 else 12 * 60


def elapsed(period, display):
    done = 0
    for older in range(1, period):
        done += period_length(older)
    remain = min(period_length(period), max(0.0, clock_seconds(display)))
    return done + (period_length(period) - remain)


def box_minutes(cell):
    text = str(cell or "").strip()
    if not text or text in {"--", "DNP", "NA"}:
        return 0.0
    if ":" in text:
        mins, secs = text.split(":", 1)
        try:
            return int(mins) + float(secs) / 60.0
        except ValueError:
            return 0.0
    try:
        return float(text)
    except ValueError:
        return 0.0


def split_made(cell):
    text = str(cell or "0-0")
    if "-" not in text:
        return 0
    made, _att = text.split("-", 1)
    try:
        return int(made)
    except ValueError:
        return 0


def dk_fp(pts, fg3m, reb, ast, stl, blk, tov):
    return pts + 0.5 * fg3m + 1.25 * reb + 1.5 * ast + 2 * stl + 2 * blk - 0.5 * tov


def empty_stats():
    return {k: 0 for k in STAT_KEYS}


def empty_pair():
    return {
        "MIN_ON": 0.0, "FP_ON": 0.0, "MIN_OFF": 0.0, "FP_OFF": 0.0, "REPL_MIN": 0.0,
        "PLAY_GP": 0, "PLAY_MIN": 0.0, "MISS_GP": 0, "MISS_MIN": 0.0,
    }


def games_on(day):
    data = get(
        "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard?dates=%s"
        % day.strftime("%Y%m%d")
    )
    out = []
    for event in data.get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        status = (comp.get("status") or {}).get("type") or {}
        if not status.get("completed"):
            continue
        teams = comp.get("competitors") or []
        by_ha = {t.get("homeAway"): t for t in teams}
        home, away = by_ha.get("home"), by_ha.get("away")
        if not home or not away:
            continue
        out.append({
            "id": str(event.get("id") or ""),
            "date": day.isoformat(),
            "home": canon((home.get("team") or {}).get("abbreviation")),
            "away": canon((away.get("team") or {}).get("abbreviation")),
        })
    return [g for g in out if g["id"]]


def team_rows(side):
    team = canon((side.get("team") or {}).get("abbreviation"))
    team_id = str((side.get("team") or {}).get("id") or "")
    stats = (side.get("statistics") or [{}])[0]
    labels = stats.get("labels") or []
    idx = {label: i for i, label in enumerate(labels)}
    rows = []
    for athlete in stats.get("athletes") or []:
        person = athlete.get("athlete") or {}
        pid = str(person.get("id") or "")
        name = person.get("displayName") or ""
        cells = athlete.get("stats") or []
        if not pid or not name:
            continue

        def cell(label):
            i = idx.get(label)
            return cells[i] if i is not None and i < len(cells) else ""

        rows.append({
            "id": pid,
            "name": name,
            "team": team,
            "team_id": team_id,
            "starter": bool(athlete.get("starter")),
            "dnp": bool(athlete.get("didNotPlay")),
            "min": 0.0 if athlete.get("didNotPlay") else box_minutes(cell("MIN")),
            "pts": int(float(cell("PTS") or 0) if str(cell("PTS") or "0").replace(".", "", 1).isdigit() else 0),
            "fg3m": split_made(cell("3PT")),
            "reb": int(float(cell("REB") or 0) if str(cell("REB") or "0").replace(".", "", 1).isdigit() else 0),
            "ast": int(float(cell("AST") or 0) if str(cell("AST") or "0").replace(".", "", 1).isdigit() else 0),
            "stl": int(float(cell("STL") or 0) if str(cell("STL") or "0").replace(".", "", 1).isdigit() else 0),
            "blk": int(float(cell("BLK") or 0) if str(cell("BLK") or "0").replace(".", "", 1).isdigit() else 0),
            "tov": int(float(cell("TO") or 0) if str(cell("TO") or "0").replace(".", "", 1).isdigit() else 0),
        })
    return rows


def add_stat(bucket, pid, kind, amount):
    if not pid or not amount:
        return
    row = bucket.setdefault(pid, empty_stats())
    row[kind] = row.get(kind, 0) + amount


def play_stats(play):
    """Return stat credits keyed by athlete id. Participant 1 is the main player."""
    text = play.get("text") or ""
    low = text.lower()
    parts = []
    for part in play.get("participants") or []:
        pid = str((part.get("athlete") or {}).get("id") or "")
        if pid:
            parts.append(pid)
    if not parts or "team rebound" in low:
        return {}
    out = {}
    score = int(play.get("scoreValue") or 0)
    is_ft = "free throw" in low
    is_fg = ("makes" in low or "misses" in low) and not is_ft and "rebound" not in low
    if play.get("scoringPlay") and score:
        add_stat(out, parts[0], "pts", score)
        if score >= 3:
            add_stat(out, parts[0], "fg3m", 1)
    if is_fg:
        add_stat(out, parts[0], "fga", 1)
    if is_ft:
        add_stat(out, parts[0], "fta", 1)
    if "assist" in low and len(parts) > 1:
        add_stat(out, parts[1], "ast", 1)
    if "rebound" in low and "team rebound" not in low:
        add_stat(out, parts[0], "reb", 1)
    if "block" in low and len(parts) > 1:
        add_stat(out, parts[1], "blk", 1)
    if "steal" in low and len(parts) > 1:
        add_stat(out, parts[1], "stl", 1)
        add_stat(out, parts[0], "tov", 1)
    elif "turnover" in low or (play.get("type") or {}).get("text", "").lower() == "lane":
        add_stat(out, parts[0], "tov", 1)
    return out


def close_replacements(open_repl, repl_seconds, now, drop):
    kept = []
    for row in open_repl:
        if drop(row):
            repl_seconds[(row["out"], row["inn"])] = repl_seconds.get((row["out"], row["inn"]), 0.0) + max(0.0, now - row["start"])
        else:
            kept.append(row)
    open_repl[:] = kept


def process_summary(summary, game):
    """Return (pairs, status). status is 'ok' or a short skip reason."""
    sides = (summary.get("boxscore") or {}).get("players") or []
    roster = {}
    by_id = {}
    lineup = {}
    for side in sides:
        rows = team_rows(side)
        if not rows:
            continue
        team_id = rows[0]["team_id"]
        roster[team_id] = rows
        starters = [r["id"] for r in rows if r["starter"] and not r["dnp"]]
        if len(starters) != 5:
            starters = [r["id"] for r in rows if r["starter"]]
        if len(starters) != 5:
            return [], "starters %s" % rows[0]["team"]
        lineup[team_id] = set(starters)
        for row in rows:
            by_id[row["id"]] = row

    plays = summary.get("plays") or []
    plays = sorted(plays, key=lambda p: int(p.get("sequenceNumber") or 0))
    if len(plays) < 80:
        return [], "short pbp"

    on_seconds = {pid: 0.0 for pid in by_id}
    pair_on = {}
    pair_off = {}
    pair_fp_on = {}
    pair_fp_off = {}
    pair_stats_on = {}
    pair_stats_off = {}
    counted = {pid: empty_stats() for pid in by_id}
    repl_seconds = {}
    open_repl = []
    last_t = 0.0
    bad_lineup = 0

    def credit_time(dt):
        if dt <= 0:
            return
        for team_id, group in lineup.items():
            present = set(group)
            for mate in present:
                on_seconds[mate] += dt
            for mate in present:
                for other in roster[team_id]:
                    if other["id"] == mate:
                        continue
                    key = (other["id"], mate)
                    if other["id"] in present:
                        pair_on[key] = pair_on.get(key, 0.0) + dt
                    else:
                        pair_off[key] = pair_off.get(key, 0.0) + dt

    def credit_split(pid, stats, fp_delta):
        player = by_id.get(pid)
        if not player:
            return
        team_id = player["team_id"]
        present = lineup.get(team_id) or set()
        for other in roster[team_id]:
            if other["id"] == pid:
                continue
            key = (other["id"], pid)
            if other["id"] in present:
                if fp_delta:
                    pair_fp_on[key] = pair_fp_on.get(key, 0.0) + fp_delta
                dest = pair_stats_on.setdefault(key, empty_stats())
            else:
                if fp_delta:
                    pair_fp_off[key] = pair_fp_off.get(key, 0.0) + fp_delta
                dest = pair_stats_off.setdefault(key, empty_stats())
            for kind, amount in (stats or {}).items():
                if amount:
                    dest[kind] = dest.get(kind, 0) + amount

    for play in plays:
        period = int((play.get("period") or {}).get("number") or 0)
        if period <= 0:
            continue
        now = elapsed(period, (play.get("clock") or {}).get("displayValue"))
        if now + 0.4 < last_t:
            now = last_t
        credit_time(now - last_t)
        last_t = now
        ptype = ((play.get("type") or {}).get("text") or "")
        if ptype == "Substitution":
            parts = []
            for part in play.get("participants") or []:
                pid = str((part.get("athlete") or {}).get("id") or "")
                if pid:
                    parts.append(pid)
            team_id = str((play.get("team") or {}).get("id") or "")
            group = lineup.get(team_id)
            if group is None or len(parts) < 2:
                bad_lineup += 1
                continue
            incoming, outgoing = parts[0], parts[1]
            close_replacements(
                open_repl,
                repl_seconds,
                now,
                lambda row, incoming=incoming, outgoing=outgoing: row["inn"] in (incoming, outgoing) or row["out"] == incoming,
            )
            if outgoing in group:
                group.remove(outgoing)
            if incoming not in group:
                group.add(incoming)
            if len(group) == 5 and incoming in group and outgoing not in group:
                open_repl.append({"out": outgoing, "inn": incoming, "start": now})
            else:
                bad_lineup += 1
            continue
        for pid, stats in play_stats(play).items():
            dest = counted.get(pid)
            if dest is None:
                continue
            for kind, amount in stats.items():
                dest[kind] = dest.get(kind, 0) + amount
            credit_split(
                pid,
                stats,
                dk_fp(stats.get("pts", 0), stats.get("fg3m", 0), stats.get("reb", 0), stats.get("ast", 0), stats.get("stl", 0), stats.get("blk", 0), stats.get("tov", 0)),
            )

    close_replacements(open_repl, repl_seconds, last_t, lambda row: True)

    minute_misses = 0
    fp_misses = 0
    for pid, player in by_id.items():
        got = on_seconds.get(pid, 0.0) / 60.0
        if player["min"] >= 8 and abs(got - player["min"]) > 3:
            minute_misses += 1
        box_fp = dk_fp(player["pts"], player["fg3m"], player["reb"], player["ast"], player["stl"], player["blk"], player["tov"])
        got_fp = dk_fp(counted[pid]["pts"], counted[pid]["fg3m"], counted[pid]["reb"], counted[pid]["ast"], counted[pid]["stl"], counted[pid]["blk"], counted[pid]["tov"])
        if box_fp >= 12 and abs(got_fp - box_fp) > max(6, box_fp * 0.18):
            fp_misses += 1
    if minute_misses > 3 or fp_misses > 4 or bad_lineup > 12:
        return [], "minutes %s fp %s subs %s" % (minute_misses, fp_misses, bad_lineup)

    pairs = []
    seen = set()
    keys = set(pair_on) | set(pair_off) | set(pair_fp_on) | set(pair_fp_off) | set(pair_stats_on) | set(pair_stats_off) | set(repl_seconds)
    for star_id, mate_id in keys:
        star = by_id.get(star_id)
        mate = by_id.get(mate_id)
        if not star or not mate or star["team"] != mate["team"]:
            continue
        if (star_id, mate_id) in seen:
            continue
        seen.add((star_id, mate_id))
        star_played = star["min"] >= 8
        mate_played = mate["min"] >= 1
        star_missed = star["min"] < 1
        pairs.append({
            "TEAM": star["team"],
            "PLAYER": star["name"],
            "TEAMMATE": mate["name"],
            "MIN_ON": pair_on.get((star_id, mate_id), 0.0) / 60.0,
            "FP_ON": pair_fp_on.get((star_id, mate_id), 0.0),
            "MIN_OFF": pair_off.get((star_id, mate_id), 0.0) / 60.0,
            "FP_OFF": pair_fp_off.get((star_id, mate_id), 0.0),
            "REPL_MIN": repl_seconds.get((star_id, mate_id), 0.0) / 60.0,
            "PTS_ON": pair_stats_on.get((star_id, mate_id), {}).get("pts", 0),
            "PTS_OFF": pair_stats_off.get((star_id, mate_id), {}).get("pts", 0),
            "REB_ON": pair_stats_on.get((star_id, mate_id), {}).get("reb", 0),
            "REB_OFF": pair_stats_off.get((star_id, mate_id), {}).get("reb", 0),
            "AST_ON": pair_stats_on.get((star_id, mate_id), {}).get("ast", 0),
            "AST_OFF": pair_stats_off.get((star_id, mate_id), {}).get("ast", 0),
            "STL_ON": pair_stats_on.get((star_id, mate_id), {}).get("stl", 0),
            "STL_OFF": pair_stats_off.get((star_id, mate_id), {}).get("stl", 0),
            "BLK_ON": pair_stats_on.get((star_id, mate_id), {}).get("blk", 0),
            "BLK_OFF": pair_stats_off.get((star_id, mate_id), {}).get("blk", 0),
            "TOV_ON": pair_stats_on.get((star_id, mate_id), {}).get("tov", 0),
            "TOV_OFF": pair_stats_off.get((star_id, mate_id), {}).get("tov", 0),
            "FG3M_ON": pair_stats_on.get((star_id, mate_id), {}).get("fg3m", 0),
            "FG3M_OFF": pair_stats_off.get((star_id, mate_id), {}).get("fg3m", 0),
            "FGA_ON": pair_stats_on.get((star_id, mate_id), {}).get("fga", 0),
            "FGA_OFF": pair_stats_off.get((star_id, mate_id), {}).get("fga", 0),
            "FTA_ON": pair_stats_on.get((star_id, mate_id), {}).get("fta", 0),
            "FTA_OFF": pair_stats_off.get((star_id, mate_id), {}).get("fta", 0),
            "PLAY_GP": 1 if star_played and mate_played else 0,
            "PLAY_MIN": mate["min"] if star_played and mate_played else 0.0,
            "MISS_GP": 1 if star_missed and mate_played else 0,
            "MISS_MIN": mate["min"] if star_missed and mate_played else 0.0,
        })
    report = {
        "game": game,
        "bad_lineup": bad_lineup,
        "minute_misses": minute_misses,
        "fp_misses": fp_misses,
        "players": [
            {
                "name": player["name"],
                "team": player["team"],
                "box": round(player["min"], 1),
                "got": round(on_seconds.get(pid, 0.0) / 60.0, 1),
            }
            for pid, player in by_id.items()
            if player["min"] >= 8
        ],
    }
    return pairs, report


def read_onoff():
    totals = {}
    if not ONOFF.exists():
        return totals
    with ONOFF.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            key = (row.get("TEAM"), row.get("PLAYER"), row.get("TEAMMATE"))
            if not all(key):
                continue
            acc = empty_pair()
            for field in acc:
                raw = row.get(field) or "0"
                acc[field] = int(float(raw)) if field.endswith("_GP") else float(raw)
            totals[key] = acc
    return totals


def read_done():
    found = {}
    if not DONE.exists():
        return found
    with DONE.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            gid = row.get("GAME_ID") or ""
            if gid:
                found[gid] = row
    return found


def add_pairs(totals, pairs):
    for row in pairs:
        key = (row["TEAM"], row["PLAYER"], row["TEAMMATE"])
        acc = totals.get(key)
        if acc is None:
            acc = empty_pair()
            totals[key] = acc
        for field, value in row.items():
            if field in {"TEAM", "PLAYER", "TEAMMATE"}:
                continue
            acc[field] += value


def write_onoff(totals):
    rows = []
    for (team, player, mate), acc in totals.items():
        if acc["MIN_ON"] < 1 and acc["MIN_OFF"] < 1 and acc["REPL_MIN"] < 1 and not acc["MISS_GP"]:
            continue
        out = {"TEAM": team, "PLAYER": player, "TEAMMATE": mate}
        for field, value in acc.items():
            if field.endswith("_GP"):
                out[field] = int(round(value))
            else:
                out[field] = round(value, 2)
        rows.append(out)
    rows.sort(key=lambda r: (r["TEAM"], r["PLAYER"], -r["REPL_MIN"], r["TEAMMATE"]))
    with ONOFF.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ONOFF_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return len(rows)


def write_done(done):
    rows = list(done.values())
    rows.sort(key=lambda r: (r.get("DATE") or "", r.get("GAME_ID") or ""))
    with DONE.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=DONE_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in DONE_FIELDS})


def check_game(game_id):
    summary = get("https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=%s" % game_id)
    pairs, report = process_summary(summary, {"id": game_id, "date": "", "home": "", "away": ""})
    if isinstance(report, str):
        print("SKIP", report)
        return
    print("bad subs", report["bad_lineup"], "minute misses", report["minute_misses"], "fp misses", report["fp_misses"])
    for row in report["players"]:
        flag = " *" if abs(row["box"] - row["got"]) > 2 else ""
        print(f"{row['team']:4} {row['name'][:24]:24} box {row['box']:5} got {row['got']:5}{flag}")
    interesting = [p for p in pairs if p["REPL_MIN"] >= 4 or p["MIN_OFF"] >= 8]
    interesting.sort(key=lambda p: -p["REPL_MIN"])
    print("pairs", len(pairs), "with a real off stint", len(interesting))
    for row in interesting[:12]:
        on_rate = row["FP_ON"] / row["MIN_ON"] if row["MIN_ON"] else 0
        off_rate = row["FP_OFF"] / row["MIN_OFF"] if row["MIN_OFF"] else 0
        print(
            f"{row['PLAYER'][:18]:18} off -> {row['TEAMMATE'][:18]:18} "
            f"repl {row['REPL_MIN']:.1f}  on {row['MIN_ON']:.1f}m {on_rate:.2f}/m  off {row['MIN_OFF']:.1f}m {off_rate:.2f}/m"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default=date.today().isoformat())
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--game", default="")
    args = parser.parse_args()
    if args.game:
        check_game(args.game)
        return

    if args.rebuild:
        totals = {}
        done = {}
    else:
        totals = read_onoff()
        done = read_done()
    if args.start:
        start = date.fromisoformat(args.start)
    elif done:
        latest = max(row.get("DATE") or "2026-10-20" for row in done.values())
        start = date.fromisoformat(latest) - timedelta(days=1)
    else:
        start = date.fromisoformat("2026-10-20")
    end = date.fromisoformat(args.end)
    added = 0
    skipped = 0
    day = start
    while day <= end:
        try:
            games = games_on(day)
        except Exception as exc:
            print("%s scoreboard failed: %s" % (day, exc))
            day += timedelta(days=1)
            continue
        pending = [g for g in games if g["id"] not in done]
        print("%s %s final, %s new" % (day, len(games), len(pending)))
        for game in pending:
            try:
                summary = get(
                    "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary?event=%s" % game["id"]
                )
                pairs, report = process_summary(summary, game)
            except Exception as exc:
                print("  %s failed: %s" % (game["id"], exc))
                time.sleep(0.3)
                continue
            status = "ok" if not isinstance(report, str) else "skip"
            if status == "ok":
                add_pairs(totals, pairs)
                added += 1
                print("  %s %s @ %s ok %s pairs" % (game["id"], game["away"], game["home"], len(pairs)))
            else:
                skipped += 1
                print("  %s %s @ %s skip %s" % (game["id"], game["away"], game["home"], report))
            done[game["id"]] = {
                "GAME_ID": game["id"],
                "DATE": game["date"],
                "HOME": game["home"],
                "AWAY": game["away"],
                "STATUS": status if status == "ok" else report,
            }
            time.sleep(0.25)
        day += timedelta(days=1)
    count = write_onoff(totals)
    write_done(done)
    print("Added %s games, skipped %s, %s on/off rows." % (added, skipped, count))


if __name__ == "__main__":
    main()
