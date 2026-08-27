"""Fetch real 2025-26 quarter-level data for the two modelled teams from ESPN.

NETWORK STEP (run manually to refresh data): this is the only script that
touches the internet. It writes a compact fixture, data/espn_2025_26_games.json,
which the OFFLINE ingest (nbadb.ingest.espn) then loads. Keeping the network out
of ingest is the same rule the game feed follows: a rebuild is a pure function
of committed data and never depends on a live endpoint.

Sources (public ESPN site API, no key required):
  schedule: .../teams/{abbr}/schedule?season=2026&seasontype=2
  summary:  .../summary?event={id}   (linescores, boxscore, play-by-play)

For each regular-season game involving BOS or OKC it records: final score,
per-quarter team linescores, each modelled team's full player box score
(including MINUTES, which the sandbox feed lacked), and per-quarter player
POINTS derived from scoring plays.
"""
import json, subprocess, pathlib, sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "espn_2025_26_games.json"
BASE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
CA = "/root/.ccr/ca-bundle.crt"
TEAMS = ["bos", "okc"]          # the two modelled teams
SEASON = 2026                   # ESPN labels 2025-26 as season 2026
BOX_LABELS = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO",
              "STL", "BLK", "OREB", "DREB", "PF", "+/-"]


def get(url, tries=3):
    last = ""
    for _ in range(tries):
        r = subprocess.run(["curl", "-sS", "--retry", "2", "--cacert", CA, url],
                           capture_output=True, text=True)
        if r.returncode == 0:
            return json.loads(r.stdout)
        last = r.stderr[:200]
    raise RuntimeError(f"curl failed for {url}: {last}")


def schedule_event_ids(abbr):
    d = get(f"{BASE}/teams/{abbr}/schedule?season={SEASON}&seasontype=2")
    ids = []
    for e in d.get("events", []):
        comp = e["competitions"][0]
        if comp.get("status", {}).get("type", {}).get("completed"):
            ids.append(e["id"])
    return ids


def parse_summary(d, want_abbrs):
    comp = d["header"]["competitions"][0]
    competitors = comp["competitors"]
    by_side = {}
    for c in competitors:
        by_side[c["homeAway"]] = {
            "abbr": c["team"]["abbreviation"],
            "score": int(c.get("score", 0)),
            "winner": c.get("winner", False),
            "linescores": [int(round(float(ls.get("displayValue", ls.get("value", 0)))))
                           for ls in c.get("linescores", [])],
        }
    home, away = by_side["home"], by_side["away"]
    # play-by-play references teams by numeric id, not abbreviation
    team_id_abbr = {c["team"]["id"]: c["team"]["abbreviation"] for c in competitors}

    # athlete id -> (name, team_abbr) and full-game box for modelled teams
    box = {}
    id_name = {}
    for tb in d.get("boxscore", {}).get("players", []):
        ab = tb["team"]["abbreviation"]
        st = tb["statistics"][0] if tb.get("statistics") else None
        if not st:
            continue
        labels = st.get("labels", BOX_LABELS)
        for a in st.get("athletes", []):
            ath = a.get("athlete") or {}
            aid = ath.get("id")
            if not aid:
                continue
            id_name[aid] = ath.get("displayName")
            if ab in want_abbrs and a.get("stats"):
                row = dict(zip(labels, a["stats"]))
                box.setdefault(ab, []).append({
                    "espn_id": aid,
                    "name": ath.get("displayName"),
                    "pos": (ath.get("position") or {}).get("abbreviation")
                           if isinstance(ath.get("position"), dict) else None,
                    "starter": a.get("starter", False),
                    "min": row.get("MIN"), "pts": row.get("PTS"),
                    "fg": row.get("FG"), "tp": row.get("3PT"), "ft": row.get("FT"),
                    "reb": row.get("REB"), "ast": row.get("AST"), "to": row.get("TO"),
                    "stl": row.get("STL"), "blk": row.get("BLK"), "pf": row.get("PF"),
                    "pm": row.get("+/-"),
                })

    # per-quarter player points from scoring plays (modelled teams only)
    pq = {}   # espn_id -> {period: {"pts":, "fgm":, "fg3m":, "ftm":}}
    for p in d.get("plays", []):
        if not p.get("scoringPlay"):
            continue
        ab = team_id_abbr.get(p.get("team", {}).get("id"))
        if ab not in want_abbrs:
            continue
        parts = p.get("participants") or []
        if not parts:
            continue
        aid = parts[0].get("athlete", {}).get("id")
        if not aid:
            continue
        per = p.get("period", {}).get("number")
        sv = int(p.get("scoreValue", 0))
        slot = pq.setdefault(aid, {}).setdefault(per, {"pts": 0, "fgm": 0, "fg3m": 0, "ftm": 0})
        slot["pts"] += sv
        if sv == 3:
            slot["fgm"] += 1; slot["fg3m"] += 1
        elif sv == 2:
            slot["fgm"] += 1
        elif sv == 1:
            slot["ftm"] += 1

    return {
        "date": comp.get("date"),
        "home": home, "away": away,
        "box": box,
        "player_quarters": pq,
        "id_name": {k: v for k, v in id_name.items() if k in pq},
    }


def main():
    ids = []
    for ab in TEAMS:
        got = schedule_event_ids(ab)
        print(f"{ab.upper()}: {len(got)} completed regular-season games", file=sys.stderr)
        ids.extend(got)
    ids = sorted(set(ids), key=int)
    print(f"unique games involving BOS/OKC: {len(ids)}", file=sys.stderr)

    want = {"BOS", "OKC"}
    games = []
    for i, eid in enumerate(ids, 1):
        try:
            d = get(f"{BASE}/summary?event={eid}")
            rec = parse_summary(d, want)
            rec["event_id"] = eid
            games.append(rec)
        except Exception as e:
            print(f"  skip {eid}: {e}", file=sys.stderr)
        if i % 20 == 0:
            print(f"  {i}/{len(ids)} fetched", file=sys.stderr)

    OUT.write_text(json.dumps({"season_id": 2025, "season_label": "2025-26",
                               "source": "espn_site_api", "teams": ["BOS", "OKC"],
                               "games": games}, separators=(",", ":")))
    kb = OUT.stat().st_size / 1024
    print(f"wrote {OUT.name}: {len(games)} games, {kb:.0f} KB", file=sys.stderr)


if __name__ == "__main__":
    main()
