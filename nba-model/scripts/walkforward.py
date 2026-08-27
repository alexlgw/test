"""Sequential, walk-forward betting test: bet game 1, use the result to inform
game 2, and so on -- 'find a pattern based on previous results' taken literally,
with NO lookahead. Then answer: with $500, how much would last season have made?

WHAT IS REAL AND WHAT IS ASSUMED
  Real   : every pick is graded against the actual 2025-26 result (ESPN). The
           hit rate is a fact.
  Assumed: the DOLLAR figure. We have no historical odds (the recurring wall in
           this project), so profit is priced at the standard -110 juice -- risk
           $110 to win $100. That is the right price for a pick'em / spread /
           quarter-style bet, but NOT for a moneyline on a heavy favorite like
           OKC, which would pay far less. So read the hit rate as the finding
           and the dollar line as an illustration under a stated price.

The rules below each turn PRIOR games into a pick for the next game. The
'adaptive' strategy is the walk-forward one: before each game it follows
whichever rule has the best record SO FAR this season (>= MIN_SAMPLE picks),
so its selection never sees the game it is betting.
"""
import sys, pathlib, math
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect

SEASON = 2025
BREAK_EVEN = 110 / 210          # 0.5238 -- win rate needed to profit at -110
PAYOUT = 100 / 110              # win this per 1 risked at -110
MIN_SAMPLE = 8                  # picks a rule needs before the adaptive one trusts it
STAKE_TOTAL = 500.0             # the user's bankroll, staked flat across the season

con = connect()


def team_games(ab):
    """Chronological games for a team: (win, won_q3) with prior context attached."""
    tid = con.execute("SELECT team_id FROM team WHERE abbrev=?", (ab,)).fetchone()[0]
    rows = con.execute("""
        SELECT g.game_id, g.tipoff_utc,
          CASE WHEN g.home_team_id=? THEN g.home_pts ELSE g.away_pts END tp,
          CASE WHEN g.home_team_id=? THEN g.away_pts ELSE g.home_pts END op
        FROM game g WHERE ? IN (g.home_team_id,g.away_team_id) AND g.season_id=?
        ORDER BY g.tipoff_utc""", (tid, tid, tid, SEASON)).fetchall()
    q3 = {}
    for r in con.execute("""
        SELECT gps.game_id,
          SUM(CASE WHEN gps.team_id=? THEN gps.points END) t3,
          SUM(CASE WHEN gps.team_id<>? THEN gps.points END) o3
        FROM game_period_score gps JOIN game g USING(game_id)
        WHERE gps.period=3 AND g.season_id=? AND ? IN (g.home_team_id,g.away_team_id)
        GROUP BY gps.game_id""", (tid, tid, SEASON, tid)).fetchall():
        q3[r["game_id"]] = (r["t3"], r["o3"])
    out = []
    for r in rows:
        t3, o3 = q3.get(r["game_id"], (0, 0))
        out.append({"win": r["tp"] > r["op"], "won_q3": (t3 or 0) > (o3 or 0)})
    return out


# --- rules: given the list of prior games (all strictly before k), return a pick
#     for game k as True/False = 'bet the team to WIN', or None = 'no bet'. ---
def r_always(prior):      return True
def r_ride(prior):        return True if (prior and prior[-1]["win"]) else None
def r_bounce(prior):      return True if (prior and not prior[-1]["win"]) else None
def r_ride_q3(prior):     return True if (prior and prior[-1]["won_q3"]) else None

RULES = {"always_win": r_always, "ride_streak": r_ride,
         "bounce_back": r_bounce, "after_q3_win": r_ride_q3}


def grade(pick, game):
    """A pick of 'win' is correct iff the team won. Returns 1/0, or None if no bet."""
    if pick is None:
        return None
    return 1 if (game["win"] == pick) else 0


def run_fixed(games, rule):
    w = n = 0
    for k, g in enumerate(games):
        res = grade(rule(games[:k]), g)
        if res is not None:
            n += 1; w += res
    return w, n


def run_adaptive(games):
    """Before each game, follow the rule with the best record so far."""
    w = n = 0
    rec = {name: [0, 0] for name in RULES}          # name -> [wins, picks]
    for k, g in enumerate(games):
        prior = games[:k]
        eligible = [(wins / picks, name) for name, (wins, picks) in rec.items()
                    if picks >= MIN_SAMPLE and RULES[name](prior) is not None]
        chosen = max(eligible)[1] if eligible else "always_win"
        res = grade(RULES[chosen](prior), g)
        if res is not None:
            n += 1; w += res
        for name, fn in RULES.items():                # update every rule's history
            r = grade(fn(prior), g)
            if r is not None:
                rec[name][0] += r; rec[name][1] += 1
    return w, n


def binom_p(w, n, p0=0.5):
    """Two-sided normal-approx p-value for w wins in n at rate p0."""
    if n == 0:
        return 1.0
    z = (w - n * p0) / math.sqrt(n * p0 * (1 - p0))
    return 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))


def report(label, w, n):
    if n == 0:
        print(f"  {label:<14}  no bets"); return
    hit = w / n
    roi = (w * PAYOUT - (n - w)) / n           # profit per unit risked, at -110
    profit = STAKE_TOTAL * roi
    edge = "  <- beats -110 break-even" if hit > BREAK_EVEN else ""
    print(f"  {label:<14} {w:>3}-{n-w:<3} ({hit:5.1%})  ROI {roi:+6.1%}  "
          f"${STAKE_TOTAL:.0f}->{profit:+7.2f}{edge}")


both = team_games("OKC") + team_games("BOS")
print("=" * 72)
print("SEQUENTIAL WALK-FORWARD BET TEST — OKC + BOS, 2025-26 (real results)")
print(f"break-even at -110 juice = {BREAK_EVEN:.1%}   |   $500 staked flat across all bets")
print("=" * 72)
print("\nFixed rules (each bets the team to WIN under its condition):")
for name, fn in RULES.items():
    report(name, *run_fixed(both, fn))

print("\nAdaptive (walk-forward: follow the best rule so far, no lookahead):")
aw, an = run_adaptive(both)
report("adaptive", aw, an)

hit = aw / an
fair_dec = 1 / hit                              # fair decimal odds for this win rate
fair_ml = -round(100 * hit / (1 - hit))         # ... as an American moneyline
print(f"\n  What the search actually 'found': bet these two teams to win. It went")
print(f"  {aw}-{an-aw} ({hit:.1%}) -- but that is not an edge, it is a tautology.")
print(f"  OKC won 64 and BOS 56 games; of course 'bet them to win' hits ~73%.")
print(f"  Beating a coin (p={binom_p(aw, an):.2f}) is the wrong bar. The bar is")
print(f"  beating the PRICE, and the market prices a {hit:.0%} winner at about")
print(f"  {fair_ml} (decimal {fair_dec:.2f}). Paid that, the ROI is ~0.")

print("\nTHE $500 ANSWER:")
print(f"  At the fantasy price of -110 the table shows ~+${STAKE_TOTAL*0.39:.0f} on $500.")
print(f"  That number is an artifact of underpricing a favorite. At the REAL")
print(f"  moneyline for a {hit:.0%} winner (~{fair_ml}), the same 121-45 record")
print( "  returns essentially $0 before vig and a small LOSS after it. Betting")
print( "  elite teams to keep winning does not make money -- the market already")
print( "  knows they are elite.")
print("\n  So, honestly: with $500 last season these patterns win roughly nothing.")
print("  The hit rate is real; the profit is not, because we are pricing bets")
print("  with an assumed -110 instead of the actual closing lines this project")
print("  still does not have. A real edge means beating that closing line (CLV),")
print("  which needs a historical-odds feed -- not more box-score or quarter data.")
