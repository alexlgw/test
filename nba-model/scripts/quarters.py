"""How each team's scoring distributes across quarters, and how the key players
score quarter by quarter. Reads the real ESPN season (load_espn.py must have run).

Per-quarter player averages divide TOTAL quarter points by games PLAYED (from the
box score), not by the number of quarters the player happened to score in -- see
the scope note in schema/007_quarters.sql.
"""
import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect

SEASON = 2025
con = connect()


def team_quarter_profile(ab):
    print("=" * 66)
    print(f"{ab} — team scoring by quarter (regulation)")
    print("=" * 66)
    print(f"  {'Q':<3}{'avg':>7}{'in wins':>9}{'in loss':>9}{'home':>8}{'away':>8}")
    rows = con.execute("SELECT * FROM v_team_quarter_scoring WHERE abbrev=? ORDER BY period", (ab,)).fetchall()
    for r in rows:
        print(f"  Q{r['period']:<2}{r['avg_pts']:>7}{r['avg_in_wins']:>9}"
              f"{r['avg_in_losses']:>9}{r['avg_home']:>8}{r['avg_away']:>8}")
    best = max(rows, key=lambda r: (r['avg_in_wins'] or 0) - (r['avg_in_losses'] or 0))
    print(f"  --> biggest win/loss gap: Q{best['period']} "
          f"({(best['avg_in_wins'] or 0) - (best['avg_in_losses'] or 0):+.1f} pts). "
          f"That quarter separates their wins from losses most.")


def games_played(ab):
    return {r["player_id"]: r["gp"] for r in con.execute(
        """SELECT pgs.player_id, COUNT(DISTINCT pgs.game_id) gp
           FROM player_game_stat pgs JOIN game g USING(game_id)
           JOIN team t ON t.team_id=pgs.team_id
           WHERE t.abbrev=? AND g.season_id=? GROUP BY pgs.player_id""",
        (ab, SEASON))}


def player_quarter_profile(ab, top=5):
    print(f"\n  {ab} — per-quarter scoring for the top rotation (pts/game played):")
    gp = games_played(ab)
    # total points per (player, quarter) from the view, pivoted
    rows = con.execute("""SELECT p.player_id, p.full_name, pps.period, SUM(pps.pts) tot
        FROM player_period_stat pps JOIN player p USING(player_id)
        JOIN team t USING(team_id) JOIN game g USING(game_id)
        WHERE t.abbrev=? AND g.season_id=? AND pps.period BETWEEN 1 AND 4
        GROUP BY p.player_id, pps.period""", (ab, SEASON)).fetchall()
    by_player = {}
    for r in rows:
        d = by_player.setdefault((r["player_id"], r["full_name"]), {})
        d[r["period"]] = r["tot"]
    # rank players by total regulation points
    ranked = sorted(by_player.items(), key=lambda kv: -sum(kv[1].values()))
    print(f"    {'player':<26}{'Q1':>6}{'Q2':>6}{'Q3':>6}{'Q4':>6}   best Q")
    for (pid, name), q in ranked[:top]:
        g = gp.get(pid, 0) or 1
        pg = {p: q.get(p, 0) / g for p in (1, 2, 3, 4)}
        bestq = max(pg, key=pg.get)
        print(f"    {name:<26}" + "".join(f"{pg[p]:>6.1f}" for p in (1, 2, 3, 4)) +
              f"    Q{bestq}")


for ab in ("OKC", "BOS"):
    team_quarter_profile(ab)
    player_quarter_profile(ab)
    print()

print("Reading: a team's per-quarter profile is a prior for quarter-level bets")
print("(1st-quarter moneyline, halftime line, 3rd-quarter spikes). The player")
print("grid shows WHEN each scorer does damage -- e.g. a bench guard who lives in")
print("Q2, a star who closes in Q4. scripts/walkforward.py turns the game-level")
print("version of this into a sequential betting test.")
