"""Parse sports-feed JSON into the schema.

Everything here is a pure function of a raw_payload row. Re-running an ingest
must produce the same database, so parsing never consults the network and never
uses the wall clock for anything that lands in a fact table.
"""
from __future__ import annotations
from ..db import land_payload, resolve_player

SOURCE = "sportradar_feed"
PERIOD_SEC = 12 * 60          # NBA quarter
OT_SEC = 5 * 60

# feed key -> our column. Anything not listed falls through to `extra`.
TEAM_MAP = {
    "points": "pts", "field_goals_made": "fgm", "field_goals_att": "fga",
    "three_points_made": "fg3m", "three_points_att": "fg3a",
    "free_throws_made": "ftm", "free_throws_att": "fta",
    "offensive_rebounds": "oreb", "defensive_rebounds": "dreb",
    "assists": "ast", "steals": "stl", "blocks": "blk",
    "total_turnovers": "tov", "personal_fouls": "pf",
    "possessions": "possessions", "offensive_rating": "off_rating",
    "defensive_rating": "def_rating", "points_in_paint": "pts_in_paint",
    "fast_break_pts": "fastbreak_pts", "second_chance_pts": "second_chance_pts",
    "bench_points": "bench_pts", "biggest_lead": "biggest_lead",
}
PLAYER_MAP = {
    "points": "pts", "field_goals_made": "fgm", "field_goals_att": "fga",
    "three_points_made": "fg3m", "three_points_att": "fg3a",
    "free_throws_made": "ftm", "free_throws_att": "fta",
    "offensive_rebounds": "oreb", "defensive_rebounds": "dreb",
    "assists": "ast", "steals": "stl", "blocks": "blk",
    "turnovers": "tov", "personal_fouls": "pf", "pls_min": "plus_minus",
    "offensive_rating": "off_rating", "defensive_rating": "def_rating",
    "usage_pct": "usage_pct", "minutes": "minutes",
}


def split_stats(raw: dict, mapping: dict):
    """Return (typed_cols, extra_json_dict). Unmapped keys are preserved, not
    dropped — the overflow is the whole point of the hybrid shape."""
    import json
    typed, extra = {}, {}
    for k, v in raw.items():
        if k in mapping:
            typed[mapping[k]] = v
        else:
            extra[k] = v
    return typed, (json.dumps(extra, sort_keys=True) if extra else None)


def upsert_team(con, abbrev, season_id, market=None, name=None):
    con.execute("INSERT OR IGNORE INTO team(abbrev,franchise_key) VALUES (?,?)",
                (abbrev, abbrev))
    tid = con.execute("SELECT team_id FROM team WHERE abbrev=?", (abbrev,)).fetchone()[0]
    con.execute("INSERT OR IGNORE INTO team_season(team_id,season_id,market,name) "
                "VALUES (?,?,?,?)", (tid, season_id, market, name))
    return tid


def ingest_game_stats(con, payload: dict, game_id: str, season_id: int,
                      tipoff_utc: str, phase_code: str = "REG") -> dict:
    """Load one game_stats response. Returns a small report dict."""
    pid = land_payload(con, SOURCE, "game_stats", game_id, payload)
    home_ab, away_ab = payload["home"], payload["away"]
    teams = payload.get("teams", {})
    home = upsert_team(con, home_ab, season_id, name=teams.get(home_ab, {}).get("name"))
    away = upsert_team(con, away_ab, season_id, name=teams.get(away_ab, {}).get("name"))
    phase = con.execute("SELECT phase_id FROM season_phase WHERE code=?", (phase_code,)).fetchone()[0]

    score = payload.get("score", {})
    periods = payload.get("scoring_by_period", {})
    con.execute("""INSERT INTO game(game_id,season_id,phase_id,home_team_id,away_team_id,
        tipoff_utc,status,home_pts,away_pts,n_periods,payload_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(game_id) DO UPDATE SET status=excluded.status,
        home_pts=excluded.home_pts, away_pts=excluded.away_pts, payload_id=excluded.payload_id""",
        (game_id, season_id, phase, home, away, tipoff_utc, payload.get("status", "closed"),
         score.get(home_ab), score.get(away_ab), len(periods) or None, pid))

    for per, d in periods.items():
        for ab, tid in ((home_ab, home), (away_ab, away)):
            con.execute("INSERT OR REPLACE INTO game_period_score(game_id,period,team_id,points) "
                        "VALUES (?,?,?,?)", (game_id, int(per), tid, d.get(ab, 0)))

    for ab, tid, opp, is_home in ((home_ab, home, away, 1), (away_ab, away, home, 0)):
        ts = payload.get("team_stats", {}).get(ab, {})
        if not ts:
            continue
        typed, extra = split_stats(ts, TEAM_MAP)
        cols = ["game_id", "team_id", "opp_team_id", "is_home", "extra", "payload_id"] + list(typed)
        vals = [game_id, tid, opp, is_home, extra, pid] + list(typed.values())
        con.execute(f"INSERT OR REPLACE INTO team_game_stat({','.join(cols)}) "
                    f"VALUES ({','.join('?'*len(cols))})", vals)

    n_players = 0
    for ab, tid in ((home_ab, home), (away_ab, away)):
        for p in payload.get("player_stats", {}).get(ab, []):
            player_id = resolve_player(con, SOURCE, p["name"], p.get("position"))
            if player_id is None:
                continue                      # parked as ambiguous, not guessed
            typed, extra = split_stats(p.get("stats", {}), PLAYER_MAP)
            cols = ["game_id", "player_id", "team_id", "position", "extra", "payload_id"] + list(typed)
            vals = [game_id, player_id, tid, p.get("position"), extra, pid] + list(typed.values())
            con.execute(f"INSERT OR REPLACE INTO player_game_stat({','.join(cols)}) "
                        f"VALUES ({','.join('?'*len(cols))})", vals)
            n_players += 1

    build_game_state(con, game_id)
    con.commit()
    return {"game_id": game_id, "payload_id": pid, "players": n_players,
            "periods": len(periods)}


def build_game_state(con, game_id: str) -> int:
    """Rebuild game_state for one game. Fully idempotent: deletes and regenerates.

    Today this can only produce PERIOD-BOUNDARY snapshots (5 per regulation
    game) because the feed carries no play-by-play. Every row is tagged
    source='period_boundary' so a model never mistakes a coarse snapshot for
    real in-game granularity. When PBP arrives, this function reads game_event
    instead and the tag becomes 'event' — no schema change, no consumer change.
    """
    con.execute("DELETE FROM game_state WHERE game_id=?", (game_id,))
    g = con.execute("SELECT home_team_id, away_team_id FROM game WHERE game_id=?",
                    (game_id,)).fetchone()
    rows = con.execute("SELECT period, team_id, points FROM game_period_score "
                       "WHERE game_id=? ORDER BY period", (game_id,)).fetchall()
    if not rows:
        return 0
    by_period = {}
    for r in rows:
        by_period.setdefault(r["period"], {})[r["team_id"]] = r["points"]
    max_p = max(by_period)
    total_sec = sum(PERIOD_SEC if p <= 4 else OT_SEC for p in range(1, max_p + 1))

    h = a = elapsed = 0
    con.execute("INSERT INTO game_state VALUES (?,?,?,?,?,?,?)",
                (game_id, 0, 1, 0, 0, 1.0, "period_boundary"))
    n = 1
    for p in sorted(by_period):
        h += by_period[p].get(g["home_team_id"], 0)
        a += by_period[p].get(g["away_team_id"], 0)
        elapsed += PERIOD_SEC if p <= 4 else OT_SEC
        con.execute("INSERT INTO game_state VALUES (?,?,?,?,?,?,?)",
                    (game_id, elapsed, p, h, a,
                     round(1 - elapsed / total_sec, 6), "period_boundary"))
        n += 1
    return n
