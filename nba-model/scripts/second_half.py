"""Second-half scoring for the key players -- the foundation of a 2H player prop.

The user's angle: bet how many points key players score in the second half. That
is a PLAYER PROP, and props (especially half-props) are the softest, least
efficient market -- the best theoretical place for an edge in this whole project.

The honest data wall: ESPN's free historical odds carry FULL-GAME player point
props, but NOT second-half player props, and the over/under side is unlabeled
and not bulk-queryable. So we cannot grade 2H prop BETS in dollars here. What we
CAN do -- and what you would need before betting one -- is measure the real
second-half scoring from play-by-play: each key player's Q3+Q4 points per game,
how consistent it is, and how the team's second-half total behaves.

A prop is bettable when the outcome is more predictable than the line implies.
So the number that matters is not the average -- the book sets the line at the
average -- it is the DISPERSION and the FLOOR: a player who reliably clears a
number is where a soft half-prop line leaks value.
"""
import sys, pathlib, statistics
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect

SEASON = 2025
con = connect()


def second_half_by_game(team, player_id):
    """List of (game_id, 2H points) for every game the player APPEARED in
    (0 included), using the box score for appearances and play-by-play for pts."""
    appeared = [r["game_id"] for r in con.execute(
        """SELECT DISTINCT pgs.game_id FROM player_game_stat pgs JOIN game g USING(game_id)
           JOIN raw_payload rp ON rp.payload_id=g.payload_id
           WHERE pgs.player_id=? AND g.season_id=? AND rp.source='espn'""",
        (player_id, SEASON))]
    pts = {r["game_id"]: r["p"] for r in con.execute(
        """SELECT game_id, SUM(pts) p FROM player_period_stat
           WHERE player_id=? AND period IN (3,4) GROUP BY game_id""", (player_id,))}
    return [(gid, pts.get(gid, 0)) for gid in appeared]


def key_players(team):
    return con.execute(
        """SELECT ps.player_id, p.full_name, ps.pts_pg
           FROM player_season_stat ps JOIN player p USING(player_id) JOIN team t USING(team_id)
           WHERE t.abbrev=? AND ps.is_key_player=1 ORDER BY ps.pts_pg DESC""", (team,)).fetchall()


def report_team(team):
    print("=" * 70)
    print(f"{team} — key players' SECOND-HALF (Q3+Q4) scoring, 2025-26")
    print("=" * 70)
    print(f"  {'player':<24}{'GP':>4}{'2H avg':>8}{'std':>6}{'min':>5}{'max':>5}"
          f"{'  line':>7}{'over%':>7}")
    for kp in key_players(team):
        vals = [v for _, v in second_half_by_game(team, kp["player_id"])]
        if not vals:
            continue
        mean = statistics.mean(vals)
        sd = statistics.pstdev(vals)
        line = round(mean - 0.5) + 0.5              # a plausible half-prop line near the mean
        over = sum(1 for v in vals if v > line) / len(vals)
        print(f"  {kp['full_name']:<24}{len(vals):>4}{mean:>8.1f}{sd:>6.1f}"
              f"{min(vals):>5}{max(vals):>5}{line:>7.1f}{over:>7.0%}")
    # team second-half total
    tot = [r["t"] for r in con.execute(
        """SELECT gps.game_id, SUM(gps.points) t
           FROM game_period_score gps JOIN game g USING(game_id)
           JOIN team tm ON tm.team_id=gps.team_id
           JOIN raw_payload rp ON rp.payload_id=g.payload_id
           WHERE tm.abbrev=? AND g.season_id=? AND gps.period IN (3,4) AND rp.source='espn'
           GROUP BY gps.game_id""", (team, SEASON))]
    print(f"  team 2nd-half total: {statistics.mean(tot):.1f} avg, "
          f"{statistics.pstdev(tot):.1f} std, range {min(tot)}-{max(tot)} over {len(tot)} games")


for t in ("OKC", "BOS"):
    report_team(t)
    print()

print("HOW TO READ THIS FOR BETTING")
print("  The 'line' column is set at each player's own 2H average, so 'over%' sits")
print("  near 50% by construction -- that is exactly how a book prices the primary")
print("  line, and why betting the average is no edge. The exploitable columns are")
print("  'std' and 'min': a low-variance scorer with a high floor (e.g. a star who")
print("  almost never dips below a number in the 2H) is where a SOFT half-prop line")
print("  -- set a hair too low because the book leans on the full-game number -- ")
print("  leaks value. That edge is real in principle and is why props are the")
print("  softest market; capturing it needs a feed that carries SECOND-HALF player")
print("  prop lines with labeled over/under, which the free ESPN data does not.")
print("  This script gives the scoring side of that bet; the price side is the gap.")
