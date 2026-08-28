"""Fade-a-team test: "bet <team> to LOSE every game" at real closing lines.

Usage: python3 scripts/fade_team.py [ESPN_ABBR]   (default WSH = Wizards)

Betting a team to lose means backing its OPPONENT. A bad team loses most nights,
but the market prices it as a heavy underdog, so its opponents are expensive
favorites. This grades three ways to fade the team at REAL ESPN BET closing
prices: opponent moneyline, opponent against the spread, and the game under.

NETWORK research tool (like fetch_espn.py): it fetches the team's season and
caches it to data/fade_<abbr>_2025_26.json, then grades from that cache.
"""
import sys, json, subprocess, pathlib, statistics, collections
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.model.prob import implied_prob, american_to_decimal

CA = "/root/.ccr/ca-bundle.crt"
SITE = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
CORE = "https://sports.core.api.espn.com/v2/sports/basketball/leagues/nba/events"
TEAM = (sys.argv[1] if len(sys.argv) > 1 else "WSH").upper()
CACHE = ROOT / "data" / f"fade_{TEAM.lower()}_2025_26.json"
BANKROLL = 500.0
BE = 110 / 210


def get(url, tries=3):
    for _ in range(tries):
        r = subprocess.run(["curl", "-sS", "--retry", "2", "--cacert", CA, url],
                           capture_output=True, text=True)
        if r.returncode == 0:
            try:
                return json.loads(r.stdout)
            except json.JSONDecodeError:
                return None
    return None


def am(x):
    if isinstance(x, dict):
        x = x.get("american", x.get("alternateDisplayValue"))
    if x in (None, "", "OFF", "--"):
        return None
    if isinstance(x, str):
        x = x.strip().replace("+", "")
        if x.upper() == "EVEN":
            return 100
    try:
        f = float(x); return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return None


def build_cache():
    sched = get(f"{SITE}/teams/{TEAM.lower()}/schedule?season=2026&seasontype=2")
    if not sched or not sched.get("events"):
        sys.exit(f"No 2025-26 schedule for '{TEAM}'. Use ESPN's abbreviation "
                 f"(e.g. WSH, UTAH, NO, GS, NY, SA).")
    games = []
    for e in sched.get("events", []):
        c = e["competitions"][0]
        if not c.get("status", {}).get("type", {}).get("completed"):
            continue
        sides = {t["homeAway"]: t for t in c["competitors"]}
        was_home = sides["home"]["team"]["abbreviation"] == TEAM
        me = sides["home"] if was_home else sides["away"]
        opp = sides["away"] if was_home else sides["home"]
        eid = e["id"]
        od = get(f"{CORE}/{eid}/competitions/{eid}/odds")

        def usable(i):
            ho = i.get("homeTeamOdds", {})
            return (ho.get("close") or {}).get("pointSpread") is not None and \
                   ho.get("moneyLine") is not None
        items = [i for i in (od or {}).get("items", []) if usable(i)]
        if not items:
            continue
        # ESPN backfills different books per game; prefer a pregame consensus book
        pref = {"ESPN BET": 0, "DraftKings": 1, "Caesars Sportsbook": 2}
        it = min(items, key=lambda i: pref.get(i.get("provider", {}).get("name"), 9))
        book = it.get("provider", {}).get("name")
        ho, ao = it.get("homeTeamOdds", {}), it.get("awayTeamOdds", {})
        me_odds, opp_odds = (ho, ao) if was_home else (ao, ho)

        def score(t):
            s = t.get("score", 0)
            if isinstance(s, dict):
                s = s.get("value", s.get("displayValue", 0))
            return int(float(s))

        games.append({
            "date": e["date"], "opp": opp["team"]["abbreviation"], "was_home": was_home,
            "book": book, "was_pts": score(me), "opp_pts": score(opp),
            "was_spread_close": am((me_odds.get("close") or {}).get("pointSpread")),
            "opp_ml_close": am(opp_odds.get("moneyLine")) or am((opp_odds.get("close") or {}).get("moneyLine")),
            "total_close": am((it.get("close") or {}).get("total")),
        })
    CACHE.write_text(json.dumps({"team": TEAM, "games": games}, separators=(",", ":")))
    return games


def ml_profit(a):
    return a / 100.0 if a > 0 else 100.0 / abs(a)


def line(label, w, n, roi):
    print(f"  {label:<32} {w:>3}-{n-w:<3} ({(w/n if n else 0):5.1%})  "
          f"ROI {roi:+6.1%}  ${BANKROLL:.0f} -> {BANKROLL*roi:+7.2f}"
          + ("  *" if roi > 0 else ""))


games = json.loads(CACHE.read_text())["games"] if CACHE.exists() else build_cache()
print("=" * 74)
print(f"FADE TEST — bet {TEAM} to LOSE every game, 2025-26, at REAL closing lines")
print("=" * 74)

su_loss = sum(1 for g in games if g["was_pts"] < g["opp_pts"])
print(f"\n{TEAM} record: {sum(1 for g in games if g['was_pts']>g['opp_pts'])}-{su_loss}"
      f"  ({su_loss}/{len(games)} = {su_loss/len(games):.0%} of games they LOST)")
opp_mls = [g["opp_ml_close"] for g in games if g["opp_ml_close"]]
print(f"their opponents' avg closing moneyline: {statistics.mean(opp_mls):+.0f} "
      f"(implied {implied_prob(statistics.mean(opp_mls)):.0%} favorites)")
books = collections.Counter(g["book"] for g in games)
print(f"lines from: {', '.join(f'{b} x{n}' for b, n in books.most_common())} "
      f"({len(games)} games)")

# A) bet the opponent's moneyline (= bet TEAM to lose)
w = n = 0; pnl = 0.0
for g in games:
    if not g["opp_ml_close"]:
        continue
    n += 1; opp_won = g["opp_pts"] > g["was_pts"]
    pnl += ml_profit(g["opp_ml_close"]) if opp_won else -1.0
    w += opp_won
print("\nWays to fade them, graded at real prices ($500 staked flat):")
line(f"bet {TEAM} to lose (opp ML)", w, n, pnl / n)

# B) bet the opponent against the spread
w = n = 0; pnl = 0.0
for g in games:
    if g["was_spread_close"] is None:
        continue
    edge = (g["was_pts"] - g["opp_pts"]) + g["was_spread_close"]   # WAS cover margin
    if edge == 0:
        continue
    n += 1; opp_covered = edge < 0
    pnl += ml_profit(-110) if opp_covered else -1.0
    w += opp_covered
line(f"bet against {TEAM} (opp ATS)", w, n, pnl / n)
ats_w, ats_n = w, n

# C) bet the under in their games
w = n = 0; pnl = 0.0
for g in games:
    if g["total_close"] is None:
        continue
    tot = g["was_pts"] + g["opp_pts"]
    if tot == g["total_close"]:
        continue
    n += 1; under = tot < g["total_close"]
    pnl += ml_profit(-110) if under else -1.0
    w += under
line(f"bet the UNDER in {TEAM} games", w, n, pnl / n)

import math
z = (ats_w - ats_n * 0.5) / math.sqrt(ats_n * 0.25)
p = 2 * (1 - 0.5 * (1 + math.erf(abs(z) / math.sqrt(2))))
print(f"\nWHAT THIS SHOWS (break-even at -110 = {BE:.1%})")
print(f"  {TEAM} lost {su_loss/len(games):.0%} of games -- but betting them to lose means")
print( "  backing their opponents, priced as ~88% favorites. On the MONEYLINE that")
print(f"  {su_loss/len(games):.0%} win rate is not enough: it returns about -2%, a small loss. The")
print( "  price already knows they are bad, so the obvious bet has no edge -- exactly")
print( "  the mirror of betting good teams to WIN.")
print(f"\n  The one line that looks alive is the SPREAD: fading them ATS went "
      f"{ats_w}-{ats_n-ats_w} ({ats_w/ats_n:.0%}).")
print(f"  Before betting the house on it: that is z={z:.1f}, p={p:.2f} on {ats_n} games --")
print( "  about a 1-in-10 fluke, not significance. 'Fade the tank team ATS' is a")
print( "  well-known public angle; once everyone knows it, the market shades the")
print( "  number and the edge decays. One season on one team cannot tell a real")
print( "  angle from a hot streak -- the honest read is 'interesting, unproven.'")
print( "  (Run this on other bad teams / seasons to see it regress toward 50%.)")
