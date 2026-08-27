"""Ingest the ESPN odds fixture into market_line (open + close, both sides).

Pure function of data/espn_odds_2025_26.json (no network). A line is a time
series, per 004_market.sql, so each selection gets an OPEN row (is_closing=0)
and a CLOSE row (is_closing=1). Closing is set here at ingest, never inferred by
MAX() later. Idempotent: closing rows are guarded by ux_line_closing, and open
rows are de-duplicated on (game, market, side, observed_at).
"""
from __future__ import annotations
from ..db import land_payload

SOURCE = "espn_core_odds"
BOOK = ("espnbet", "ESPN BET", "soft", 1)      # code, name, class, licensed


def _book_id(con):
    con.execute("INSERT OR IGNORE INTO book(code,display_name,class,is_licensed_us) "
                "VALUES (?,?,?,?)", BOOK)
    return con.execute("SELECT book_id FROM book WHERE code=?", (BOOK[0],)).fetchone()[0]


def _team_id(con, ab):
    r = con.execute("SELECT team_id FROM team WHERE abbrev=?", (ab,)).fetchone()
    return r[0] if r else None


def _line(con, game_id, book_id, market, side, handicap, price, observed_at, closing, payload):
    if price is None:
        return 0
    # keep at most one open and one close per selection (idempotent re-ingest)
    con.execute("""DELETE FROM market_line WHERE game_id=? AND book_id=? AND market=?
                   AND side=? AND is_closing=?""",
                (game_id, book_id, market, side, closing))
    con.execute("""INSERT INTO market_line(game_id,book_id,market,side,handicap,
        price_american,observed_at,is_closing,payload_id)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (game_id, book_id, market, side, handicap, int(round(price)),
         observed_at, closing, payload))
    return 1


def ingest_odds(con, doc: dict) -> dict:
    book_id = _book_id(con)
    n = 0
    for g in doc["games"]:
        eid = g["event_id"]
        if con.execute("SELECT 1 FROM game WHERE game_id=?", (eid,)).fetchone() is None:
            continue                                   # only odds for games we hold
        payload = land_payload(con, SOURCE, "odds", eid, g)
        home, away = _team_id(con, g["home"]), _team_id(con, g["away"])
        if home is None or away is None:
            continue
        hs, ha = str(home), str(away)
        open_at = g["date"][:10] + "T12:00Z"           # opening line, pregame
        close_at = g["date"]                            # closing line, at tipoff

        sp, ml, tot = g["spread"], g["moneyline"], g["total"]
        juice = sp.get("juice") or -110
        # spread (handicap = the number; price = the juice)
        n += _line(con, eid, book_id, "spread", hs, sp["open_home"], juice, open_at, 0, payload)
        n += _line(con, eid, book_id, "spread", ha, sp["open_away"], juice, open_at, 0, payload)
        n += _line(con, eid, book_id, "spread", hs, sp["close_home"], juice, close_at, 1, payload)
        n += _line(con, eid, book_id, "spread", ha, sp["close_away"], juice, close_at, 1, payload)
        # moneyline (price = the ml; no handicap)
        n += _line(con, eid, book_id, "ml", hs, None, ml["open_home"], open_at, 0, payload)
        n += _line(con, eid, book_id, "ml", ha, None, ml["open_away"], open_at, 0, payload)
        n += _line(con, eid, book_id, "ml", hs, None, ml["close_home"], close_at, 1, payload)
        n += _line(con, eid, book_id, "ml", ha, None, ml["close_away"], close_at, 1, payload)
        # total (handicap = the number; price = over/under juice)
        n += _line(con, eid, book_id, "total", "over", tot["open"], -110, open_at, 0, payload)
        n += _line(con, eid, book_id, "total", "under", tot["open"], -110, open_at, 0, payload)
        n += _line(con, eid, book_id, "total", "over", tot["close"], tot.get("over_odds", -110), close_at, 1, payload)
        n += _line(con, eid, book_id, "total", "under", tot["close"], tot.get("under_odds", -110), close_at, 1, payload)

    con.commit()
    return {"games": len(doc["games"]), "lines": n}
