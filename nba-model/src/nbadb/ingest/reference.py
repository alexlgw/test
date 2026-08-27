"""Ingest season-level reference (enrichment) data.

Same provenance discipline as the game feed: the document is landed verbatim in
raw_payload (source='web_reference', one payload per team so a single team can
be re-fetched without touching the other), and every derived row points back to
its payload. Re-running is idempotent.

The only transform applied here is percent -> fraction for shooting splits, so
that ts_pct/fg_pct sit on the same scale as the generated columns in 003.
"""
from __future__ import annotations
from ..db import land_payload, resolve_player

SOURCE = "web_reference"


def _frac(pct):
    """47.7 (percent, as sources present it) -> 0.477 (fraction, as the DB stores)."""
    return None if pct is None else round(pct / 100.0, 4)


def ingest_enrichment(con, doc: dict) -> dict:
    """Load a season enrichment document. Returns a small report dict."""
    meta = doc["meta"]
    season_id = meta["season_id"]
    as_of = meta["as_of_date"]
    n_teams = n_players = 0

    for tm in doc["teams"]:
        ab = tm["abbrev"]
        payload = land_payload(con, SOURCE, "team_season",
                               f"{ab}:{season_id}:{as_of}", tm)

        con.execute("INSERT OR IGNORE INTO team(abbrev,franchise_key) VALUES (?,?)",
                    (ab, ab))
        tid = con.execute("SELECT team_id FROM team WHERE abbrev=?", (ab,)).fetchone()[0]
        con.execute("INSERT OR IGNORE INTO team_season(team_id,season_id,market,name,conference) "
                    "VALUES (?,?,?,?,?)",
                    (tid, season_id, tm.get("market"), tm.get("name"), tm.get("conference")))

        con.execute("""INSERT INTO team_season_stat(
            team_id,season_id,as_of_date,games,wins,losses,
            home_wins,home_losses,away_wins,away_losses,
            off_rating,def_rating,pace,srs,conference,conf_rank,source,source_url,payload_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(team_id,season_id,as_of_date) DO UPDATE SET
              games=excluded.games, wins=excluded.wins, losses=excluded.losses,
              home_wins=excluded.home_wins, home_losses=excluded.home_losses,
              away_wins=excluded.away_wins, away_losses=excluded.away_losses,
              off_rating=excluded.off_rating, def_rating=excluded.def_rating,
              pace=excluded.pace, srs=excluded.srs, conference=excluded.conference,
              conf_rank=excluded.conf_rank, source=excluded.source,
              source_url=excluded.source_url, payload_id=excluded.payload_id""",
            (tid, season_id, as_of, tm["games"], tm["wins"], tm["losses"],
             tm.get("home_wins"), tm.get("home_losses"),
             tm.get("away_wins"), tm.get("away_losses"),
             tm.get("off_rating"), tm.get("def_rating"), tm.get("pace"), tm.get("srs"),
             tm.get("conference"), tm.get("conf_rank"),
             tm.get("source", SOURCE), tm.get("source_url"), payload))
        n_teams += 1

        team_games = tm["games"]
        for pl in tm.get("players", []):
            player_id = resolve_player(con, SOURCE, pl["name"], pl.get("pos"))
            if player_id is None:
                continue                        # ambiguous -> parked, never guessed
            con.execute("""INSERT INTO player_season_stat(
                player_id,team_id,season_id,as_of_date,games_played,team_games,
                min_pg,pts_pg,reb_pg,ast_pg,fg_pct,fg3_pct,ts_pct,
                is_key_player,avail_note,source,source_url,payload_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(player_id,team_id,season_id,as_of_date) DO UPDATE SET
                  games_played=excluded.games_played, team_games=excluded.team_games,
                  min_pg=excluded.min_pg, pts_pg=excluded.pts_pg, reb_pg=excluded.reb_pg,
                  ast_pg=excluded.ast_pg, fg_pct=excluded.fg_pct, fg3_pct=excluded.fg3_pct,
                  ts_pct=excluded.ts_pct, is_key_player=excluded.is_key_player,
                  avail_note=excluded.avail_note, source=excluded.source,
                  source_url=excluded.source_url, payload_id=excluded.payload_id""",
                (player_id, tid, season_id, as_of, pl.get("gp"), team_games,
                 pl.get("min"), pl.get("pts"), pl.get("reb"), pl.get("ast"),
                 _frac(pl.get("fg")), _frac(pl.get("fg3")), _frac(pl.get("ts")),
                 1 if pl.get("key") else 0, pl.get("note"),
                 tm.get("source", SOURCE), tm.get("source_url"), payload))
            n_players += 1

    con.commit()
    return {"teams": n_teams, "players": n_players}
