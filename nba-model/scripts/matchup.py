"""Turn the enriched season data into a win-probability estimate.

This is the point of the enrichment: a single game's box score cannot tell you
who is likely to win the NEXT game. Season-level efficiency (net rating), the
home/road split, pace, and key-player availability can. This script reads the
`v_team_strength` and `v_key_player_availability` views and produces a
transparent, defensible estimate for a given matchup.

Method (deliberately simple and inspectable, not a black box):
  expected_margin = (home.net_rating - away.net_rating) + HOME_COURT
  win_prob(home)  = Phi(expected_margin / MARGIN_SD)
where Phi is the normal CDF. MARGIN_SD ~ 12 points is the long-run standard
deviation of an NBA game result around its expectation; HOME_COURT ~ 2.5 points
is the league-average home edge. Both are shown so they can be tuned.

The estimate is a PRIOR from full-season strength. It is not a bet: it carries
no market line, and the availability caveats it prints (a star who played 20%
of the season inflates a team's season rating relative to who will actually be
on the floor) are exactly the judgement a raw number hides.
"""
import sys, pathlib, math
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect

HOME_COURT = 2.5      # points, league-average home edge
MARGIN_SD = 12.0      # points, SD of game result around expectation


def phi(x):
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def strength(con, abbrev):
    r = con.execute("SELECT * FROM v_team_strength WHERE abbrev=?", (abbrev,)).fetchone()
    if r is None:
        sys.exit(f"No enriched strength row for {abbrev}. Run `make enrich` first.")
    return r


def key_players(con, abbrev):
    return con.execute("SELECT * FROM v_key_player_availability WHERE abbrev=?",
                       (abbrev,)).fetchall()


def card(r):
    print(f"  {r['abbrev']}  {r['wins']}-{r['losses']} ({r['win_pct']:.3f})   "
          f"ORtg {r['off_rating']:.1f}  DRtg {r['def_rating']:.1f}  "
          f"Net {r['net_rating']:+.1f}  Pace {r['pace']:.1f}")
    print(f"        home {r['home_win_pct']:.3f}   away {r['away_win_pct']:.3f}   "
          f"({r['conference']} #{r['conf_rank']})")


def availability(con, abbrev):
    print(f"\n  {abbrev} key players (availability caveats):")
    for p in key_players(con, abbrev):
        flag = "  <-- limited" if (p["avail_rate"] or 0) < 0.75 else ""
        print(f"    {p['full_name']:<26} {p['games_played']:>2}/{p['team_games']} "
              f"({p['avail_rate']:.0%})  {p['pts_pg']:.1f}p/{p['reb_pg']:.1f}r/"
              f"{p['ast_pg']:.1f}a  TS {p['ts_pct']:.3f}{flag}")


def matchup(con, home_ab, away_ab):
    h, a = strength(con, home_ab), strength(con, away_ab)
    print("=" * 66)
    print(f"MATCHUP  {away_ab} (away)  @  {home_ab} (home)")
    print("=" * 66)
    card(h)
    card(a)

    margin = (h["net_rating"] - a["net_rating"]) + HOME_COURT
    p_home = phi(margin / MARGIN_SD)
    print(f"\n  Expected margin ({home_ab}): "
          f"({h['net_rating']:+.1f} - {a['net_rating']:+.1f}) + {HOME_COURT:.1f} home "
          f"= {margin:+.1f} pts")
    print(f"  Win probability   {home_ab} {p_home:.1%}   |   {away_ab} {1-p_home:.1%}")
    print(f"  (fair moneyline   {home_ab} {american(p_home)}   {away_ab} {american(1-p_home)})")

    availability(con, home_ab)
    availability(con, away_ab)

    print("\n  Read this with the caveats, not past them: a season net rating is")
    print("  inflated by games a now-limited star played. The availability lines")
    print("  above are where judgement enters -- the model gives the prior, you")
    print("  price the roster that will actually take the floor.")


def american(p):
    """Fair (vig-free) American moneyline from a probability."""
    if p <= 0 or p >= 1:
        return "n/a"
    return f"{-round(100*p/(1-p)):+d}" if p >= 0.5 else f"{round(100*(1-p)/p):+d}"


if __name__ == "__main__":
    home = sys.argv[1] if len(sys.argv) > 1 else "OKC"
    away = sys.argv[2] if len(sys.argv) > 2 else "BOS"
    con = connect()
    matchup(con, home, away)
