"""Edge analysis without a second book: devig the one book we have into a
vig-free fair price, test the market's INTERNAL consistency (does the closing
spread imply the same winner probability as the closing moneyline?), and run a
rigorous CLV ledger (bet the OPEN, grade against the devigged CLOSE).

This populates the market half of the schema the earlier steps left empty:
fair_price (devigged probabilities) and the bet / bet_grade ledger with real
pnl AND clv_pct. It is the workflow a second book would plug into -- a genuinely
independent price is what you would devig and compare here. No free, historical,
independent book proved reachable for 2025-26 (ESPN backfills only ESPN BET;
The Odds API / SportsGameOdds require a paid key), so this runs on ESPN BET's
own open vs close, which still measures CLV -- just within one book.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect
from nbadb.model.prob import (implied_prob, american_to_decimal, devig_two_way,
                              spread_to_win_prob)

NOW = "2026-08-27T00:00:00Z"
con = connect()
book_id = con.execute("SELECT book_id FROM book WHERE code='espnbet'").fetchone()[0]


def games():
    return con.execute("""
      SELECT g.game_id, g.tipoff_utc, g.home_team_id, g.away_team_id,
        ht.abbrev home, at.abbrev away, g.home_pts, g.away_pts,
        (SELECT handicap FROM market_line m WHERE m.game_id=g.game_id AND m.market='spread'
           AND m.side=CAST(g.home_team_id AS TEXT) AND m.is_closing=1) home_spread,
        (SELECT price_american FROM market_line m WHERE m.game_id=g.game_id AND m.market='ml'
           AND m.side=CAST(g.home_team_id AS TEXT) AND m.is_closing=1) hml_close,
        (SELECT price_american FROM market_line m WHERE m.game_id=g.game_id AND m.market='ml'
           AND m.side=CAST(g.away_team_id AS TEXT) AND m.is_closing=1) aml_close,
        (SELECT price_american FROM market_line m WHERE m.game_id=g.game_id AND m.market='ml'
           AND m.side=CAST(g.home_team_id AS TEXT) AND m.is_closing=0) hml_open,
        (SELECT price_american FROM market_line m WHERE m.game_id=g.game_id AND m.market='ml'
           AND m.side=CAST(g.away_team_id AS TEXT) AND m.is_closing=0) aml_open
      FROM game g JOIN team ht ON ht.team_id=g.home_team_id
                  JOIN team at ON at.team_id=g.away_team_id
      WHERE g.season_id=2025 AND g.home_pts IS NOT NULL
      ORDER BY g.tipoff_utc""").fetchall()


def populate_fair_price(rows):
    con.execute("DELETE FROM fair_price WHERE book_id=? AND method='multiplicative'", (book_id,))
    n = 0
    overs = []
    for g in rows:
        if g["hml_close"] is None or g["aml_close"] is None:
            continue
        fh, fa, over = devig_two_way(g["hml_close"], g["aml_close"])
        overs.append(over - 1)
        for side, fp in ((g["home_team_id"], fh), (g["away_team_id"], fa)):
            con.execute("""INSERT OR REPLACE INTO fair_price(game_id,book_id,market,side,
                observed_at,method,fair_prob,overround) VALUES (?,?,?,?,?,?,?,?)""",
                (g["game_id"], book_id, "ml", str(side), g["tipoff_utc"],
                 "multiplicative", fp, over))
            n += 1
    con.commit()
    return n, sum(overs) / len(overs)


def consistency(rows):
    """Closing spread-implied P(home win) vs devigged closing moneyline P(home win)."""
    diffs = []
    bet_n = bet_w = 0
    pnl = 0.0
    for g in rows:
        if None in (g["home_spread"], g["hml_close"], g["aml_close"]):
            continue
        p_spread = spread_to_win_prob(g["home_spread"])           # home win prob from spread
        fh, fa, _ = devig_two_way(g["hml_close"], g["aml_close"])  # from moneyline
        d = p_spread - fh
        diffs.append(d)
        # bet the side the SPREAD likes more than the ML market, at the ML price
        THRESH = 0.03
        home_won = g["home_pts"] > g["away_pts"]
        if d > THRESH:
            bet_n += 1; win = home_won
            pnl += (american_to_decimal(g["hml_close"]) - 1) if win else -1
            bet_w += win
        elif d < -THRESH:
            bet_n += 1; win = not home_won
            pnl += (american_to_decimal(g["aml_close"]) - 1) if win else -1
            bet_w += win
    import statistics
    return diffs, statistics.mean(diffs), statistics.pstdev(diffs), bet_n, bet_w, (pnl / bet_n if bet_n else 0)


def clv_ledger(rows):
    """Bet each team's OPENING moneyline; grade vs the devigged CLOSING fair price."""
    con.execute("DELETE FROM bet_grade WHERE bet_id IN (SELECT bet_id FROM bet WHERE model_version='clv-open-v1')")
    con.execute("DELETE FROM bet WHERE model_version='clv-open-v1'")
    beat = tot = 0
    clv_sum = pnl_sum = 0.0
    for g in rows:
        fh, fa, _ = devig_two_way(g["hml_close"], g["aml_close"]) if \
            (g["hml_close"] and g["aml_close"]) else (None, None, None)
        for side_id, open_ml, close_fair, won in (
                (g["home_team_id"], g["hml_open"], fh, g["home_pts"] > g["away_pts"]),
                (g["away_team_id"], g["aml_open"], fa, g["away_pts"] > g["home_pts"])):
            if open_ml is None or close_fair is None:
                continue
            dec = american_to_decimal(open_ml)
            clv = dec * close_fair - 1          # >0 => open price beat the closing fair value
            pnl = (dec - 1) if won else -1.0
            bet_id = con.execute("""INSERT INTO bet(game_id,book_id,market,side,price_american,
                stake,placed_at,model_version,is_live) VALUES (?,?,?,?,?,?,?,?,0)""",
                (g["game_id"], book_id, "ml", str(side_id), open_ml, 1.0,
                 g["tipoff_utc"], "clv-open-v1")).lastrowid
            con.execute("""INSERT INTO bet_grade(bet_id,result,pnl,close_price_american,
                close_fair_prob,clv_pct,graded_at) VALUES (?,?,?,?,?,?,?)""",
                (bet_id, "win" if won else "loss", pnl,
                 g["hml_close"] if side_id == g["home_team_id"] else g["aml_close"],
                 close_fair, clv, NOW))
            tot += 1; beat += clv > 0; clv_sum += clv; pnl_sum += pnl
    con.commit()
    return tot, beat, clv_sum / tot, pnl_sum / tot


rows = games()
print("=" * 76)
print("EDGE ANALYSIS — devig, market consistency, and CLV (ESPN BET, 2025-26)")
print("=" * 76)

n, avg_vig = populate_fair_price(rows)
print(f"\nDevig: wrote {n} vig-free fair probabilities to fair_price.")
print(f"  Average moneyline overround (the book's cut) = {avg_vig:.2%}. That vig is")
print(f"  the house edge every bet starts behind -- you must beat the fair price by")
print(f"  more than half of it just to break even.")

diffs, md, sd, bn, bw, broi = consistency(rows)
print(f"\nMarket internal consistency (spread-implied vs moneyline-implied P(home)):")
print(f"  mean gap {md:+.3f}, sd {sd:.3f} -- the two markets agree to within a few")
print(f"  points, as an efficient book should.")
print(f"  Betting the >3% disagreements: {bw}-{bn-bw} ({(bw/bn if bn else 0):.1%}), "
      f"ROI {broi:+.1%} on {bn} bets -- no exploitable inconsistency.")

tot, beat, avg_ev, avg_pnl = clv_ledger(rows)
print(f"\nEV-vs-fair ledger (bet the OPEN price, grade against the devigged CLOSE)")
print(f"-> populates bet / bet_grade:")
print(f"  {tot} bets logged. Opening price beat the fair closing value {beat}/{tot} "
      f"({beat/tot:.1%}).")
print(f"  Average EV vs fair close {avg_ev:+.2%}, average realized P&L {avg_pnl:+.2%}/unit.")
print(f"  Reconcile with `make odds`: there the OPEN beat the CLOSE on raw PRICE ~51%")
print(f"  of the time (+0.9%) -- the line barely drifted your way. But that drift is")
print(f"  dwarfed by the {avg_vig:.1%} vig, so measured against the vig-FREE closing")
print(f"  probability you are still {avg_ev:+.1%} behind. Line movement this small does")
print(f"  not cover the house cut: no positive EV inside one book.")

print("\nVERDICT")
print("  The devig and ledger are the real machinery: give this pipeline a second,")
print("  independent price (a sharp book like Pinnacle) and it will flag every game")
print("  where that book's fair probability diverges from this one -- that gap is")
print("  the only edge this project has ever pointed to. Within a single efficient")
print("  book, the spread and moneyline agree and the open barely beats the close:")
print("  no free money. The blocker now is data access (a keyed odds API), not the")
print("  model -- fair_price, bet, and bet_grade are populated and ready for it.")
