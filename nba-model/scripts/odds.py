"""Odds analysis: grade the season against REAL ESPN closing lines.

This is the piece the project has been missing. With actual opening and closing
prices in market_line, "how much would $500 have made" stops being an assumption
and becomes a graded result. Everything below is priced at the real ESPN BET
closing line (moneyline / spread / total), except the explicit CLV demo, which
bets the OPENING price and measures it against the close.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect

BANKROLL = 500.0
con = connect()


def ml_profit(american, stake=1.0):
    """Profit (excl. stake) on a winning American-odds bet."""
    return stake * (american / 100.0 if american > 0 else 100.0 / abs(american))


def team_rows(ab=None):
    """Rows for the modelled teams only (the view also holds their opponents)."""
    q = ("SELECT * FROM v_team_result_vs_line "
         "WHERE team_spread_close IS NOT NULL AND abbrev IN ('OKC','BOS')")
    if ab:
        q += f" AND abbrev='{ab}'"
    return con.execute(q + " ORDER BY tipoff_utc").fetchall()


def modelled_games():
    """One row per game involving OKC or BOS (for game-level bets like totals)."""
    return con.execute("""SELECT * FROM v_closing_line
        WHERE (home IN ('OKC','BOS') OR away IN ('OKC','BOS'))
        ORDER BY tipoff_utc""").fetchall()


def pricing(ab):
    r = team_rows(ab)
    spreads = [x["team_spread_close"] for x in r]
    mls = [x["team_ml_close"] for x in r if x["team_ml_close"] is not None]
    fav = sum(1 for s in spreads if s < 0)
    print(f"  {ab}: {len(r)} games | avg closing spread {sum(spreads)/len(spreads):+.1f} | "
          f"favored {fav}/{len(r)} ({fav/len(r):.0%}) | avg ML "
          f"{sum(mls)/len(mls):+.0f} (implied {implied(sum(mls)/len(mls)):.0%})")


def implied(american):
    return 100.0/(american+100) if american > 0 else abs(american)/(abs(american)+100)


def records(ab):
    r = team_rows(ab)
    su = sum(x["won"] for x in r)
    cov = push = 0
    ov = un = tpush = 0
    for x in r:
        edge = (x["pts"] - x["opp_pts"]) + x["team_spread_close"]
        cov += edge > 0; push += edge == 0
        if x["total_close"] is not None:
            ov += x["total_pts"] > x["total_close"]
            un += x["total_pts"] < x["total_close"]
            tpush += x["total_pts"] == x["total_close"]
    n = len(r)
    atsn = n - push
    print(f"  {ab}: SU {su}-{n-su} ({su/n:.0%}) | "
          f"ATS {cov}-{atsn-cov} ({cov/atsn:.0%}) | "
          f"O/U {ov}-{un}" + (f"-{tpush}P" if tpush else "") +
          f" (over {ov/(ov+un):.0%})")


def strategy(label, rows, pick):
    """pick(row) -> ('ml', team_american) | ('spread',) | ('over',)|('under',) | None."""
    n = wins = losses = pushes = 0
    pnl = 0.0
    for x in rows:
        p = pick(x)
        if p is None:
            continue
        n += 1
        if p[0] == "ml":
            won = x["won"] == 1
            pnl += ml_profit(p[1]) if won else -1.0
            wins += won; losses += not won
        elif p[0] in ("cover", "fade_spread"):
            edge = (x["pts"] - x["opp_pts"]) + x["team_spread_close"]
            edge = edge if p[0] == "cover" else -edge
            if edge == 0:
                pushes += 1; n -= 1; continue
            won = edge > 0
            pnl += ml_profit(-110) if won else -1.0
            wins += won; losses += not won
    if n == 0:
        print(f"  {label:<34} no bets"); return
    roi = pnl / n
    print(f"  {label:<34} {wins:>3}-{losses:<3} ({wins/n:5.1%})  "
          f"ROI {roi:+6.1%}  ${BANKROLL:.0f} staked -> {BANKROLL*roi:+7.2f}")


def total_strategy(label, games, side):
    """Grade an over/under bet once per game (totals are game-level)."""
    n = wins = losses = 0
    pnl = 0.0
    for x in games:
        if x["total_close"] is None:
            continue
        diff = x["total_pts"] - x["total_close"]
        diff = diff if side == "over" else -diff
        if diff == 0:
            continue
        n += 1; won = diff > 0
        pnl += ml_profit(-110) if won else -1.0
        wins += won; losses += not won
    roi = pnl / n
    print(f"  {label:<34} {wins:>3}-{losses:<3} ({wins/n:5.1%})  "
          f"ROI {roi:+6.1%}  ${BANKROLL:.0f} staked -> {BANKROLL*roi:+7.2f}")


both = team_rows()
print("=" * 74)
print("ODDS ANALYSIS — OKC + BOS 2025-26, graded at REAL ESPN closing lines")
print("=" * 74)

print("\nHow the market priced them:")
for ab in ("OKC", "BOS"):
    pricing(ab)

print("\nReal records against the closing line:")
for ab in ("OKC", "BOS"):
    records(ab)

print("\nStrategies graded at REAL closing prices ($500 staked flat across bets):")
strategy("bet each team ML to WIN",   both, lambda x: ("ml", x["team_ml_close"]) if x["team_ml_close"] else None)
strategy("bet each team ATS (cover)", both, lambda x: ("cover",))
strategy("fade them ATS (opp covers)", both, lambda x: ("fade_spread",))
games = modelled_games()
total_strategy("bet the UNDER every game", games, "under")
total_strategy("bet the OVER every game",  games, "over")

# ---- CLV: bet the OPENING moneyline, measure against the CLOSE ----
print("\nCLV demo — bet each team's OPENING moneyline, grade vs the CLOSE:")
beat = tot = 0
clv_sum = 0.0
for x in con.execute("""SELECT g.game_id,
      CASE WHEN g.home_team_id=t.team_id THEN 1 ELSE 0 END is_home, t.abbrev,
      (SELECT price_american FROM market_line m WHERE m.game_id=g.game_id AND m.market='ml'
         AND m.side=CAST(t.team_id AS TEXT) AND m.is_closing=0) open_ml,
      (SELECT price_american FROM market_line m WHERE m.game_id=g.game_id AND m.market='ml'
         AND m.side=CAST(t.team_id AS TEXT) AND m.is_closing=1) close_ml
    FROM game g JOIN team t ON t.team_id IN (g.home_team_id,g.away_team_id)
    WHERE g.season_id=2025 AND t.abbrev IN ('OKC','BOS')""").fetchall():
    if x["open_ml"] is None or x["close_ml"] is None:
        continue
    open_dec = 1 + ml_profit(x["open_ml"])
    close_dec = 1 + ml_profit(x["close_ml"])
    clv = open_dec / close_dec - 1        # >0 means you got a better price than close
    clv_sum += clv; tot += 1; beat += clv > 0
print(f"  bet {tot} opening MLs | beat the close {beat}/{tot} ({beat/tot:.0%}) | "
      f"avg CLV {clv_sum/tot:+.2%}")

print("\nWHAT THIS SHOWS")
print("  - The $500 answer, priced for real: betting both teams to win at their")
print("    ACTUAL moneylines nets about +$18 on $500 over the whole season -- a")
print("    rounding error, not a system. The 73% win rate looks huge but the price")
print("    (OKC averaged -852!) already charges you for it. This is what an")
print("    efficient closing line does: it prices the favorite correctly.")
print("  - The only lines that beat break-even here -- BOS unders (55%) and BOS ATS")
print("    (60%) -- are single-season blips on ~82 games, well inside noise. Bet")
print("    them next year expecting regression, not a repeat.")
print("  - CLV is the real test, and it came in at +0.9% (beat the close 51% of the")
print("    time) -- statistically nothing. Betting these two favorites gave no")
print("    systematic edge over the closing number. A genuine operation captures")
print("    CLV by betting BEFORE the close and logging every bet against it, which")
print("    the bet/bet_grade ledger and fair_price devig (004) are built to record.")
print("  - Bottom line across all four steps of this project: with only public")
print("    data, there is no edge in betting good teams to win. The edge, if it")
print("    exists, is in price -- finding stale opening numbers before the market")
print("    corrects them -- and proving that needs many books, not just one.")
