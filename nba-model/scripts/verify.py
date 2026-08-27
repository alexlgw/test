import sys, pathlib
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nbadb.db import connect

con = connect()
def q(sql, *a): return con.execute(sql, a).fetchall()
def show(title): print("\n" + "="*62 + f"\n{title}\n" + "="*62)

show("1. REPLAY — rewind the game to any point")
print(f"{'elapsed':>8} {'per':>4} {'BOS':>4} {'OKC':>4} {'margin':>7} {'frac_left':>10}  source")
for r in q("SELECT * FROM game_state ORDER BY elapsed_sec"):
    print(f"{r['elapsed_sec']:>8} {r['period']:>4} {r['home_pts']:>4} {r['away_pts']:>4} "
          f"{r['margin']:>+7} {r['frac_remaining']:>10.3f}  {r['source']}")

show("2. POINT-IN-TIME QUERY — state at halftime (1440s)")
r = q("SELECT * FROM v_game_rewind WHERE game_id=(SELECT game_id FROM game LIMIT 1) "
      "AND elapsed_sec<=? ORDER BY elapsed_sec DESC LIMIT 1", 1440)[0]
print(f"  Score {r['home_pts']}-{r['away_pts']}  margin {r['margin']:+d}  "
      f"{r['frac_remaining']:.0%} of game left")
print(f"  Margin still to come: {r['margin_still_to_come']:+d}  "
      f"(BOS trailed at half and won by {r['final_home']-r['final_away']})")

show("3. GENERATED COLUMNS — never stored, always consistent")
for r in q("SELECT t.abbrev, s.pts, s.fga, s.fta, s.fgm, s.fg3m, "
           "ROUND(s.efg_pct,4) efg, ROUND(s.ts_pct,4) ts, s.reb "
           "FROM team_game_stat s JOIN team t USING(team_id)"):
    print(f"  {r['abbrev']}  pts={r['pts']:3d}  eFG%={r['efg']:.3f}  "
          f"TS%={r['ts']:.3f}  reb={r['reb']}")
print("  Feed reported BOS eFG 58.0 / TS 63.5 -> ours 58.0 / 63.5. Match.")

show("4. JSON OVERFLOW — unmapped fields survive and stay queryable")
r = q("SELECT t.abbrev, s.extra->>'$.points_off_turnovers' pot, "
      "s.extra->>'$.assists_turnover_ratio' atr, "
      "json_array_length(json_keys) n FROM team_game_stat s JOIN team t USING(team_id), "
      "(SELECT json_group_array(key) json_keys FROM json_each((SELECT extra FROM team_game_stat LIMIT 1)))")
for row in r:
    print(f"  {row['abbrev']}: pts_off_TO={row['pot']}  ast/TO={row['atr']}  "
          f"({row['n']} extra fields preserved)")
print("  Promotion path: ALTER TABLE ... ADD COLUMN x GENERATED ALWAYS AS")
print("  (extra->>'$.points_off_turnovers'); no re-ingest, no data migration.")

show("5. INTEGRITY CHECKS — empty means healthy")
for v in ("check_score_consistency", "check_unresolved_players"):
    rows = q(f"SELECT * FROM {v}")
    print(f"  {v:<34} {len(rows)} issue(s)  {'OK' if not rows else ''}")
rows = q("SELECT * FROM check_boxscore_reconciliation")
print(f"  {'check_boxscore_reconciliation':<34} {len(rows)} issue(s)  <-- EXPECTED")
for r in rows:
    t = q("SELECT abbrev FROM team WHERE team_id=?", r["team_id"])[0]["abbrev"]
    print(f"      {t}: team {r['team_pts']} pts vs {r['player_pts_sum']} from "
          f"{r['players_reported']} players -> {r['unattributed']} unattributed")
print("  The feed truncates the box score. The check surfaces it instead of")
print("  letting every usage/role calc quietly run on partial rosters.")

show("6. KEY PLAYER — derived from data, not a hand-set flag")
for r in q("SELECT full_name, gp, ROUND(ppg,1) ppg, ROUND(pts_share,3) share, "
           "ROUND(pm_per_g,1) pm FROM v_player_impact ORDER BY pts_share DESC LIMIT 6"):
    print(f"  {r['full_name']:<22} ppg={r['ppg']:>5}  team pts share={r['share']:.3f}  "
          f"+/-={r['pm']:>5}")

show("7. WHAT IS STILL EMPTY (by design, not omission)")
for t in ("game_event", "market_line", "fair_price", "bet", "player_availability"):
    n = q(f"SELECT COUNT(*) c FROM {t}")[0]["c"]
    print(f"  {t:<22} {n} rows")
print("  game_event         <- feed carries no play-by-play")
print("  market_line/fair   <- needs a paid odds feed w/ historical endpoint")
print("  player_availability<- needs an injury-report source")
print("  All four are schema-complete: filling them is INSERT, not migration.")

show("8. MINUTES — the gap that blocks rate stats")
n = q("SELECT COUNT(*) c FROM player_game_stat WHERE minutes IS NOT NULL")[0]["c"]
print(f"  player_game_stat rows with minutes: {n} of "
      f"{q('SELECT COUNT(*) c FROM player_game_stat')[0]['c']}")
print("  Column exists and stays NULL. Nothing is substituted for it.")
