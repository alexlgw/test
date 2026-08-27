"""Ingest the real ESPN season fixture (data/espn_2025_26_games.json).

Pure function of the committed fixture -- no network, same rule as feed.py. The
fixture is produced separately by scripts/fetch_espn.py. Each game is landed in
raw_payload (source='espn') and parsed into the existing game / period-score /
player-box tables plus the new player_period_stat. Idempotent.
"""
from __future__ import annotations
from ..db import land_payload, resolve_player

SOURCE = "espn"


def _pair(s):
    """'9-16' -> (9, 16); '' or '--' -> (None, None)."""
    if not s or "-" not in s:
        return (None, None)
    a, b = s.split("-", 1)
    try:
        return (int(a), int(b))
    except ValueError:
        return (None, None)


def _int(s):
    try:
        return int(s)
    except (TypeError, ValueError):
        return None


def ingest_espn_games(con, doc: dict) -> dict:
    season_id = doc["season_id"]
    phase = con.execute("SELECT phase_id FROM season_phase WHERE code='REG'").fetchone()[0]
    modelled = set(doc.get("teams", []))
    n_games = n_pbox = n_pq = 0

    for g in doc["games"]:
        eid = g["event_id"]
        payload = land_payload(con, SOURCE, "summary", eid, g)
        home_ab, away_ab = g["home"]["abbr"], g["away"]["abbr"]

        def team_id(ab):
            con.execute("INSERT OR IGNORE INTO team(abbrev,franchise_key) VALUES (?,?)", (ab, ab))
            tid = con.execute("SELECT team_id FROM team WHERE abbrev=?", (ab,)).fetchone()[0]
            con.execute("INSERT OR IGNORE INTO team_season(team_id,season_id) VALUES (?,?)",
                        (tid, season_id))
            return tid

        home_id, away_id = team_id(home_ab), team_id(away_ab)
        home_ls, away_ls = g["home"]["linescores"], g["away"]["linescores"]
        n_periods = max(len(home_ls), len(away_ls))

        con.execute("""INSERT INTO game(game_id,season_id,phase_id,home_team_id,away_team_id,
            tipoff_utc,status,home_pts,away_pts,n_periods,payload_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(game_id) DO UPDATE SET home_pts=excluded.home_pts,
              away_pts=excluded.away_pts, n_periods=excluded.n_periods,
              payload_id=excluded.payload_id""",
            (eid, season_id, phase, home_id, away_id, g["date"], "closed",
             g["home"]["score"], g["away"]["score"], n_periods, payload))

        for ls, tid in ((home_ls, home_id), (away_ls, away_id)):
            for i, pts in enumerate(ls, start=1):
                con.execute("INSERT OR REPLACE INTO game_period_score(game_id,period,team_id,points) "
                            "VALUES (?,?,?,?)", (eid, i, tid, pts))

        # full-game player box (BOS/OKC only) -- carries MINUTES, unlike the feed
        for ab, tid in ((home_ab, home_id), (away_ab, away_id)):
            if ab not in modelled:
                continue
            for pl in g["box"].get(ab, []):
                pid = resolve_player(con, SOURCE, pl["name"], pl.get("pos"))
                if pid is None:
                    continue
                fgm, fga = _pair(pl.get("fg"))
                fg3m, fg3a = _pair(pl.get("tp"))
                ftm, fta = _pair(pl.get("ft"))
                con.execute("""INSERT INTO player_game_stat(
                    game_id,player_id,team_id,position,started,minutes,pts,
                    fgm,fga,fg3m,fg3a,ftm,fta,ast,tov,stl,blk,pf,plus_minus,payload_id)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(game_id,player_id) DO UPDATE SET minutes=excluded.minutes,
                      pts=excluded.pts, payload_id=excluded.payload_id""",
                    (eid, pid, tid, pl.get("pos"), 1 if pl.get("starter") else 0,
                     _int(pl.get("min")), _int(pl.get("pts")), fgm, fga, fg3m, fg3a,
                     ftm, fta, _int(pl.get("ast")), _int(pl.get("to")), _int(pl.get("stl")),
                     _int(pl.get("blk")), _int(pl.get("pf")), _int(pl.get("pm")), payload))
                n_pbox += 1

        # per-quarter player scoring, resolved through espn ids -> our player_id
        id_name = g.get("id_name", {})
        for aid, periods in g.get("player_quarters", {}).items():
            name = id_name.get(aid)
            if not name:
                continue
            pid = resolve_player(con, SOURCE, name)
            if pid is None:
                continue
            # a scorer's team: whichever modelled team they boxed for this game
            tid = home_id if any(b["espn_id"] == aid for b in g["box"].get(home_ab, [])) else \
                  (away_id if any(b["espn_id"] == aid for b in g["box"].get(away_ab, [])) else None)
            if tid is None:
                continue
            for per, s in periods.items():
                con.execute("""INSERT INTO player_period_stat(
                    game_id,player_id,team_id,period,pts,fgm,fg3m,ftm,payload_id)
                    VALUES (?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(game_id,player_id,period) DO UPDATE SET
                      pts=excluded.pts, fgm=excluded.fgm, fg3m=excluded.fg3m,
                      ftm=excluded.ftm, payload_id=excluded.payload_id""",
                    (eid, pid, tid, int(per), s["pts"], s["fgm"], s["fg3m"], s["ftm"], payload))
                n_pq += 1

        from .feed import build_game_state
        build_game_state(con, eid)

    con.commit()
    return {"games": len(doc["games"]), "player_box_rows": n_pbox, "player_quarter_rows": n_pq}
