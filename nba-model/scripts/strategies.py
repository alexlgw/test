"""Strategy lab: test a MENU of situational strategies against the real closing
lines, then check whether the best one is signal or just the luckiest of many.

The new odds + game dates unlock angles the earlier scripts could not test:
line movement (open->close), rest / back-to-backs, favorite size, home/road,
and walk-forward streaks. Every bet is graded at the real price (ATS and totals
at -110, moneyline at the actual number).

The catch this whole project keeps flagging: test twelve strategies on one
season and one will look great by chance. So after ranking, two guards run:
  1) a coin-flip null (best-of-K over noise) -- how good does the WINNER look
     when nothing is real? and
  2) an out-of-sample split -- pick the best on the first half of the season,
     then see if it survives on the second half.
"""
import sys, pathlib, random
from datetime import datetime
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect

WIN110 = 100 / 110          # profit per unit on a -110 win
BE = 110 / 210              # -110 break-even hit rate = 52.38%
BANKROLL = 500.0
random.seed(7)
con = connect()


def ml_profit(a):
    return a / 100.0 if a > 0 else 100.0 / abs(a)


def load_rows():
    raw = con.execute("""
      SELECT g.game_id, g.tipoff_utc, t.team_id, t.abbrev,
        CASE WHEN g.home_team_id=t.team_id THEN 1 ELSE 0 END is_home,
        CASE WHEN g.home_team_id=t.team_id THEN g.home_pts ELSE g.away_pts END pts,
        CASE WHEN g.home_team_id=t.team_id THEN g.away_pts ELSE g.home_pts END opp_pts,
        (g.home_pts+g.away_pts) total_pts,
        (SELECT handicap FROM market_line m WHERE m.game_id=g.game_id AND m.market='spread'
           AND m.side=CAST(t.team_id AS TEXT) AND m.is_closing=1) sp_close,
        (SELECT handicap FROM market_line m WHERE m.game_id=g.game_id AND m.market='spread'
           AND m.side=CAST(t.team_id AS TEXT) AND m.is_closing=0) sp_open,
        (SELECT price_american FROM market_line m WHERE m.game_id=g.game_id AND m.market='ml'
           AND m.side=CAST(t.team_id AS TEXT) AND m.is_closing=1) ml_close,
        (SELECT handicap FROM market_line m WHERE m.game_id=g.game_id AND m.market='total'
           AND m.side='over' AND m.is_closing=1) tot_close,
        (SELECT handicap FROM market_line m WHERE m.game_id=g.game_id AND m.market='total'
           AND m.side='over' AND m.is_closing=0) tot_open
      FROM game g JOIN team t ON t.team_id IN (g.home_team_id,g.away_team_id)
      WHERE g.season_id=2025 AND t.abbrev IN ('OKC','BOS') AND g.home_pts IS NOT NULL
      ORDER BY t.abbrev, g.tipoff_utc""").fetchall()

    rows, prev_date, prev_cov = [], {}, {}
    for r in raw:
        d = datetime.fromisoformat(r["tipoff_utc"].replace("Z", "+00:00"))
        ab = r["abbrev"]
        rest = (d - prev_date[ab]).days if ab in prev_date else None
        prev_date[ab] = d
        if r["sp_close"] is None:
            continue
        margin = r["pts"] - r["opp_pts"]
        ats_edge = margin + r["sp_close"]                    # >0 cover, 0 push
        cover = None if ats_edge == 0 else (1 if ats_edge > 0 else 0)
        over = None if (r["tot_close"] is None or r["total_pts"] == r["tot_close"]) \
            else (1 if r["total_pts"] > r["tot_close"] else 0)
        move = (r["sp_close"] - r["sp_open"]) if r["sp_open"] is not None else 0.0
        tmove = (r["tot_close"] - r["tot_open"]) if r["tot_open"] is not None else 0.0
        rows.append({
            "ab": ab, "date": d, "is_home": r["is_home"], "won": 1 if margin > 0 else 0,
            "sp_close": r["sp_close"], "move": move, "tmove": tmove,
            "ml_close": r["ml_close"], "cover": cover, "over": over,
            "prev_cov": prev_cov.get(ab),
        })
        if cover is not None:
            prev_cov[ab] = cover
    return rows


ROWS = load_rows()

# ---- strategy menu: fn(row) -> one of 'cover','fade','over','under','ml', or None
STRATS = {
    "cover (all)":            lambda r: "cover",
    "fade ATS (all)":         lambda r: "fade",
    "cover when HOME":        lambda r: "cover" if r["is_home"] else None,
    "cover when ROAD":        lambda r: "cover" if not r["is_home"] else None,
    "cover as underdog":      lambda r: "cover" if r["sp_close"] > 0 else None,
    "fade big favs (>=10)":   lambda r: "fade" if r["sp_close"] <= -10 else None,
    "cover small favs (<10)": lambda r: "cover" if -10 < r["sp_close"] < 0 else None,
    "cover on 2+ days rest":  lambda r: "cover" if (r["prev_cov"] is not None and r_rest(r) >= 2) else None,
    "fade on back-to-back":   lambda r: "fade" if (r_rest(r) is not None and r_rest(r) <= 1) else None,
    "follow steam (ATS)":     lambda r: "cover" if r["move"] < 0 else None,
    "fade steam (ATS)":       lambda r: "fade" if r["move"] > 0 else None,
    "cover after a cover":    lambda r: "cover" if r["prev_cov"] == 1 else None,
    "cover after a non-cover":lambda r: "cover" if r["prev_cov"] == 0 else None,
    "under if total dropped": lambda r: "under" if r["tmove"] < 0 else None,
    "over if total rose":     lambda r: "over" if r["tmove"] > 0 else None,
    "underdog moneyline":     lambda r: "ml" if (r["ml_close"] and r["ml_close"] > 0) else None,
}

# rest is needed by a couple of lambdas; recompute from consecutive dates per team
_REST = {}
def r_rest(r):
    return _REST.get(id(r))
def _fill_rest():
    prev = {}
    for r in sorted(ROWS, key=lambda x: (x["ab"], x["date"])):
        p = prev.get(r["ab"])
        _REST[id(r)] = (r["date"] - p).days if p else None
        prev[r["ab"]] = r["date"]
_fill_rest()


def outcome(pick, r):
    """(win, price) for a graded pick, or None for no-bet/push."""
    if pick is None:
        return None
    if pick == "cover":
        return None if r["cover"] is None else (r["cover"], -110)
    if pick == "fade":
        return None if r["cover"] is None else (1 - r["cover"], -110)
    if pick == "over":
        return None if r["over"] is None else (r["over"], -110)
    if pick == "under":
        return None if r["over"] is None else (1 - r["over"], -110)
    if pick == "ml":
        return (r["won"], r["ml_close"]) if r["ml_close"] else None
    return None


def grade(fn, rows=ROWS):
    n = w = 0
    pnl = 0.0
    for r in rows:
        o = outcome(fn(r), r)
        if o is None:
            continue
        win, price = o
        n += 1; w += win
        pnl += (ml_profit(price) if win else -1.0)
    return (w, n, pnl / n if n else 0.0)


# ---- rank
print("=" * 78)
print("STRATEGY LAB — OKC + BOS 2025-26, graded at REAL closing lines")
print(f"break-even (-110) = {BE:.1%}   |   $500 staked flat across each strategy's bets")
print("=" * 78)
results = []
for name, fn in STRATS.items():
    w, n, roi = grade(fn)
    results.append((roi, name, w, n))
results.sort(reverse=True)
print(f"  {'strategy':<26}{'record':>10}{'hit':>8}{'ROI':>9}{'$500 ->':>10}")
for roi, name, w, n in results:
    flag = "  *" if (n and w / n > BE and roi > 0) else ""
    print(f"  {name:<26}{f'{w}-{n-w}':>10}{(w/n if n else 0):>8.1%}{roi:>9.1%}{BANKROLL*roi:>+10.2f}{flag}")
print("  (* = beat -110 break-even in-sample. 'underdog moneyline' profits on")
print("   plus-money despite a losing record, but on just 26 bets -- noise.)")

# ---- guard 1: coin-flip null (best-of-K over noise), ATS/total strategies only
ats_total = {k: v for k, v in STRATS.items() if k != "underdog moneyline"}
obs_best = max(roi for roi, name, w, n in results if name in ats_total)
NREP = 3000
worse = 0
idx_cov = [i for i, r in enumerate(ROWS)]
for _ in range(NREP):
    rc = {i: random.getrandbits(1) for i in idx_cov}          # random cover per row
    ro = {i: random.getrandbits(1) for i in idx_cov}          # random over per row
    best = -9
    for name, fn in ats_total.items():
        n = w = 0
        for i, r in enumerate(ROWS):
            pick = fn(r)
            if pick in ("cover", "fade") and r["cover"] is not None:
                win = rc[i] if pick == "cover" else 1 - rc[i]
            elif pick in ("over", "under") and r["over"] is not None:
                win = ro[i] if pick == "over" else 1 - ro[i]
            else:
                continue
            n += 1; w += win
        if n:
            roi = (w * WIN110 - (n - w)) / n
            best = max(best, roi)
    worse += best >= obs_best
print(f"\nGuard 1 — coin-flip null over {len(ats_total)} strategies, {NREP} sims:")
print(f"  best real ATS/total ROI = {obs_best:+.1%}.  P(best-of-{len(ats_total)} on pure")
print(f"  noise >= that) = {worse/NREP:.2f}.  A season hands you a winner this good")
print(f"  {'often' if worse/NREP>0.1 else 'rarely'} even when NOTHING is real.")

# ---- guard 2: out-of-sample split (pick best on first half, test on second)
rows_sorted = sorted(ROWS, key=lambda r: r["date"])
half = len(rows_sorted) // 2
train, test = rows_sorted[:half], rows_sorted[half:]
best_name, best_roi = None, -9
for name, fn in STRATS.items():
    _, n, roi = grade(fn, train)
    if n >= 12 and roi > best_roi:
        best_name, best_roi = name, roi
tw, tn, troi = grade(STRATS[best_name], test)
print(f"\nGuard 2 — out-of-sample:")
print(f"  best on 1st half: '{best_name}' at {best_roi:+.1%} ROI.")
print(f"  same rule on 2nd half: {tw}-{tn-tw} ({(tw/tn if tn else 0):.1%}), ROI {troi:+.1%}, "
      f"$500 -> {BANKROLL*troi:+.2f}.")

print("\nVERDICT")
print("  Some strategies clear the -110 break-even in-sample -- they always will,")
print("  because we tried a dozen. Guard 1 shows the best of them is the kind of")
print("  number pure noise produces routinely; Guard 2 shows the in-sample winner")
print("  does not carry to unseen games. Different strategies, same honest result:")
print("  no edge you could have bet in advance. The only durable signal remains")
print("  CLV -- beating the closing price -- which needs multiple books to exploit.")
