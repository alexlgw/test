"""
Two-team NBA betting backtest.
Demonstrates pattern mining, the multiple-comparisons trap, and what actually survives.
"""
import numpy as np, pandas as pd
rng = np.random.default_rng(20260827)

BREAKEVEN = 100/210          # -110 both sides -> 52.381%
SD_M = 11.6

# ---------------------------------------------------------------- real data
# Actual completed games returned by the sports feed (2025-26 season tail + playoffs).
REAL = [
 # (date, team, opp, home?, team_pts, opp_pts)
 ("2026-03-20","BOS","MEM",0,117,112),("2026-03-22","BOS","MIN",1, 92,102),
 ("2026-03-25","BOS","OKC",1,119,109),("2026-03-27","BOS","ATL",1,109,102),
 ("2026-03-29","BOS","CHA",0,114, 99),("2026-03-30","BOS","ATL",0,102,112),
 ("2026-04-01","BOS","MIA",0,147,129),("2026-04-03","BOS","MIL",0,133,101),
 ("2026-04-05","BOS","TOR",1,115,101),("2026-04-07","BOS","CHA",1,113,102),
 ("2026-04-09","BOS","NYK",0,106,112),("2026-04-10","BOS","NOP",1,144,118),
 ("2026-04-12","BOS","ORL",1,113,108),("2026-04-19","BOS","PHI",1,123, 91),
 ("2026-04-21","BOS","PHI",1, 97,111),("2026-04-24","BOS","PHI",0,108,100),
 ("2026-04-26","BOS","PHI",0,128, 96),("2026-04-28","BOS","PHI",1, 97,113),
 ("2026-04-30","BOS","PHI",0, 93,106),("2026-05-02","BOS","PHI",1,100,109),
 ("2026-04-12","NYK","CHA",1, 96,110),("2026-04-18","NYK","ATL",1,113,102),
 ("2026-04-20","NYK","ATL",1,106,107),("2026-04-23","NYK","ATL",0,108,109),
 ("2026-04-25","NYK","ATL",0,114, 98),("2026-04-28","NYK","ATL",1,126, 97),
 ("2026-04-30","NYK","ATL",0,140, 89),("2026-05-04","NYK","PHI",1,137, 98),
 ("2026-05-06","NYK","PHI",1,108,102),("2026-05-08","NYK","PHI",0,108, 94),
 ("2026-05-10","NYK","PHI",0,144,114),("2026-05-19","NYK","CLE",1,115,104),
 ("2026-05-21","NYK","CLE",1,109, 93),("2026-05-23","NYK","CLE",0,121,108),
 ("2026-05-25","NYK","CLE",0,130, 93),("2026-06-03","NYK","SAS",0,105, 95),
 ("2026-06-05","NYK","SAS",0,105,104),("2026-06-08","NYK","SAS",1,111,115),
 ("2026-06-10","NYK","SAS",1,107,106),("2026-06-13","NYK","SAS",0, 94, 90),
]
real = pd.DataFrame(REAL, columns=["date","team","opp","home","pf","pa"])
real["margin"] = real.pf - real.pa
real["won"] = real.margin > 0

print("="*66)
print("STEP 1 — WHAT THE REAL DATA CAN AND CANNOT DO")
print("="*66)
for t in ["BOS","NYK"]:
    d = real[real.team==t]
    print(f"{t}: {len(d)} completed games  |  {d.won.sum()}-{(~d.won).sum()}  "
          f"|  avg margin {d.margin.mean():+.1f}")
print("\nColumns available from the feed:", list(real.columns))
print("Columns required to grade a bet: point_spread, closing_line, price")
print(">>> MISSING. Scores alone cannot evaluate a wager. A 15-2 team is 'good';")
print(">>> whether they were a profitable BET depends entirely on the number")
print(">>> attached to them, which this feed does not carry.\n")

# ------------------------------------------------- simulated full season
# Two teams, 82 games each. Lines are generated from the SAME truth used to
# generate outcomes, plus small noise. By construction there is NO pattern
# to find beyond a flat -4.5% vig drag. Anything we "discover" is noise.
def season(team, team_rating, n=82):
    opp = rng.normal(0, 3.4, n)
    home = rng.integers(0,2,n)
    rest = rng.choice([0,1,2,3], n, p=[.17,.42,.28,.13])   # days rest
    b2b  = (rest==0).astype(int)
    true_margin = team_rating - opp + 2.7*home - 1.4*b2b
    # bookmaker sets the spread with modest error, rounds to half point
    spread = np.round((true_margin + rng.normal(0,.9,n))*2)/2
    actual = true_margin + rng.normal(0, SD_M, n)
    return pd.DataFrame(dict(team=team, g=np.arange(1,n+1), home=home, rest=rest,
        b2b=b2b, opp_rating=opp, spread=spread, actual=np.round(actual),
        cover=(actual - spread) > 0))

sim = pd.concat([season("BOS", 4.6), season("NYK", 5.9)], ignore_index=True)
sim["month"] = ((sim.g-1)//14).clip(0,5)
# rolling form (prior games only - no lookahead)
sim["prev_cover"] = sim.groupby("team").cover.shift(1)
sim["last3"] = sim.groupby("team").cover.transform(lambda s: s.shift(1).rolling(3).sum())
sim["prev_margin"] = sim.groupby("team").actual.shift(1)
sim["fav"] = sim.spread > 0
sim["big_fav"] = sim.spread > 7
sim["dog"] = sim.spread < 0

# ------------------------------------------------- candidate pattern library
PATTERNS = {
 "Home games":                      lambda d: d.home==1,
 "Road games":                      lambda d: d.home==0,
 "As favorite":                     lambda d: d.fav,
 "As underdog":                     lambda d: d.dog,
 "Favored by 7+":                   lambda d: d.big_fav,
 "On zero days rest (B2B)":         lambda d: d.b2b==1,
 "On 2+ days rest":                 lambda d: d.rest>=2,
 "After a cover":                   lambda d: d.prev_cover==1,
 "After a non-cover":               lambda d: d.prev_cover==0,
 "After covering 3 straight":       lambda d: d.last3==3,
 "After failing 3 straight":        lambda d: d.last3==0,
 "After a 15+ pt win":              lambda d: d.prev_margin>=15,
 "After a 10+ pt loss":             lambda d: d.prev_margin<=-10,
 "Home favorite":                   lambda d: (d.home==1)&d.fav,
 "Road underdog":                   lambda d: (d.home==0)&d.dog,
 "Home dog":                        lambda d: (d.home==1)&d.dog,
 "Road favorite":                   lambda d: (d.home==0)&d.fav,
 "B2B road":                        lambda d: (d.b2b==1)&(d.home==0),
 "Rested favorite":                 lambda d: (d.rest>=2)&d.fav,
 "Vs above-avg opponent":           lambda d: d.opp_rating>0,
 "Vs below-avg opponent":           lambda d: d.opp_rating<0,
 "First half of season":            lambda d: d.month<=2,
 "Second half of season":           lambda d: d.month>=3,
 "Road dog after a loss":           lambda d: (d.home==0)&d.dog&(d.prev_cover==0),
}

def roi(w, n):
    """profit per $1 risked at -110"""
    return (w*(100/110) - (n-w)) / n if n else 0.0

# ------------------------------------------------- split
train = sim[sim.g<=55]        # first 55 games each = 110
test  = sim[sim.g> 55]        # last 27 each = 54

print("="*66)
print("STEP 2 — MINE 24 PATTERNS ON THE TRAINING HALF")
print("="*66)
rows=[]
for name, f in PATTERNS.items():
    d = train[f(train).fillna(False)]
    n, w = len(d), int(d.cover.sum())
    if n < 15: continue
    rows.append((name, n, w, w/n, roi(w,n)))
res = pd.DataFrame(rows, columns=["pattern","n","wins","rate","roi"]).sort_values("rate", ascending=False)
print(res.head(8).to_string(index=False,
      formatters={"rate":"{:.1%}".format,"roi":"{:+.1%}".format}))
best = res.iloc[0]
print(f"\nBEST IN-SAMPLE: {best.pattern}")
print(f"  {best.wins}-{best.n-best.wins}  ({best.rate:.1%} ATS)   ROI {best.roi:+.1%}")
print(f"  Break-even is {BREAKEVEN:.1%}. That looks like a real, large edge.")

# ------------------------------------------------- out of sample
print("\n" + "="*66)
print("STEP 3 — RUN THAT SAME PATTERN ON THE HELD-OUT HALF")
print("="*66)
f = PATTERNS[best.pattern]
d = test[f(test).fillna(False)]
n2, w2 = len(d), int(d.cover.sum())
print(f"{best.pattern}: {w2}-{n2-w2} ({w2/n2:.1%} ATS)   ROI {roi(w2,n2):+.1%}"
      if n2 else "no qualifying games")
print(f"\n  In-sample {best.rate:.1%}  ->  out-of-sample {w2/n2:.1%}"
      f"   [drop of {(best.rate-w2/n2)*100:.1f} points]")

# top-5 all out of sample
print("\nTop 5 in-sample patterns, tested out of sample:")
oos=[]
for _,r in res.head(5).iterrows():
    dd = test[PATTERNS[r.pattern](test).fillna(False)]
    if len(dd)<8: continue
    oos.append((r.pattern, r.rate, len(dd), dd.cover.sum()/len(dd), roi(int(dd.cover.sum()),len(dd))))
o = pd.DataFrame(oos, columns=["pattern","in_sample","n_oos","oos_rate","oos_roi"])
print(o.to_string(index=False, formatters={"in_sample":"{:.1%}".format,
      "oos_rate":"{:.1%}".format,"oos_roi":"{:+.1%}".format}))
print(f"\nMean out-of-sample rate of the 5 'best' patterns: {o.oos_rate.mean():.1%}")

# ------------------------------------------------- why: multiple comparisons
print("\n" + "="*66)
print("STEP 4 — WHAT PURE NOISE PRODUCES WHEN YOU TEST 24 RULES")
print("="*66)
print("Replace every outcome with a literal coin flip. Re-run the same search.")
sizes = res.n.values
trials, tops = 4000, []
for _ in range(trials):
    rates=[]
    for nn in sizes:
        rates.append(rng.binomial(nn,0.5)/nn)
    tops.append(max(rates))
tops=np.array(tops)
print(f"  Best-of-24 rule on coin flips:  median {np.median(tops):.1%}"
      f"   90th pct {np.percentile(tops,90):.1%}   max {tops.max():.1%}")
print(f"  P(best-of-24 >= your {best.rate:.1%} by chance alone) = {(tops>=best.rate).mean():.1%}")
print(f"\n  A single rule at {best.rate:.1%} over {best.n} games has p = "
      f"{1-0.5*(1+np.math.erf((best.wins-best.n/2)/np.sqrt(best.n/4)/np.sqrt(2))):.3f} on its own,")
print(f"  but you did not test one rule. You tested 24 and reported the winner.")

# ------------------------------------------------- what does survive
print("\n" + "="*66)
print("STEP 5 — THE ONE THING THAT DOES SURVIVE OUT OF SAMPLE")
print("="*66)
print("Instead of mining outcomes, shop prices. Same 164 games, but now each")
print("game gets a sharp fair line and 4 soft books quoting around it.\n")
sharp_fair = 0.5 + rng.normal(0,.004,len(sim))          # true cover prob ~ 50%
soft = np.array([sharp_fair + rng.normal(0,.030,len(sim)) for _ in range(4)])
soft_price = 1/np.clip(soft*1.045,.02,.98)              # decimal, 4.5% hold
best_price = soft_price.max(axis=0)
edge = sharp_fair*(best_price-1) - (1-sharp_fair)
play = edge > 0.01                                       # only bet 1%+ edge
res_cov = sim.cover.values
pnl = np.where(res_cov, best_price-1, -1)[play]
print(f"  Games qualifying (>=1% edge):  {play.sum()} of {len(sim)}")
print(f"  Average modelled edge:         {edge[play].mean():+.2%}")
print(f"  Realized ROI:                  {pnl.mean():+.2%}")
print(f"  Beat the closing fair price:   {(best_price[play] > 1/sharp_fair[play]).mean():.0%} of bets")
print(f"\n  Note the last line. CLV is ~100% because we bought below fair BY")
print(f"  CONSTRUCTION. The ROI is noisy at n={play.sum()}; the CLV is not.")
print("  That is the entire argument for grading on price instead of results.")
print("="*66)
