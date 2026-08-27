-- 005_derived.sql : views. Nothing here stores data.
-- Views over tables, never tables over views: if a number can be computed,
-- computing it is cheaper than keeping two copies honest.

-- ------------------------------------------------------------ integrity
-- Run these after every ingest. Empty result set = healthy.
CREATE VIEW check_score_consistency AS
SELECT g.game_id,
       g.home_pts, SUM(CASE WHEN ps.team_id = g.home_team_id THEN ps.points END) AS home_from_periods,
       g.away_pts, SUM(CASE WHEN ps.team_id = g.away_team_id THEN ps.points END) AS away_from_periods
FROM game g JOIN game_period_score ps USING (game_id)
WHERE g.status = 'closed'
GROUP BY g.game_id
HAVING home_from_periods <> g.home_pts OR away_from_periods <> g.away_pts;

CREATE VIEW check_boxscore_reconciliation AS
-- Player points should sum to team points. They will NOT, whenever the feed
-- truncates the player list (it returned 8-9 players for a game where 10+
-- played). Surfacing that gap is the point: silent truncation would otherwise
-- poison every usage and role calculation downstream.
SELECT t.game_id, t.team_id, t.pts AS team_pts,
       SUM(p.pts) AS player_pts_sum,
       t.pts - SUM(p.pts) AS unattributed,
       COUNT(p.player_id) AS players_reported
FROM team_game_stat t
LEFT JOIN player_game_stat p ON p.game_id = t.game_id AND p.team_id = t.team_id
GROUP BY t.game_id, t.team_id
HAVING unattributed <> 0 OR players_reported < 8;

CREATE VIEW check_unresolved_players AS
SELECT source, observed_name, status FROM player_alias WHERE status <> 'resolved';

-- ------------------------------------------------------------ team results
CREATE VIEW v_team_game AS
SELECT g.game_id, g.season_id, g.tipoff_utc, g.phase_id,
       s.team_id, s.opp_team_id, s.is_home,
       s.pts, o.pts AS opp_pts,
       s.pts - o.pts AS margin,
       CASE WHEN s.pts > o.pts THEN 1 ELSE 0 END AS won,
       s.pts + o.pts AS total_pts,
       s.possessions, s.off_rating, s.def_rating,
       -- Rest days: computed, not stored. Storing it would go stale the moment
       -- a game is postponed and re-scheduled.
       CAST(julianday(g.tipoff_utc) - julianday(
            LAG(g.tipoff_utc) OVER (PARTITION BY s.team_id, g.season_id ORDER BY g.tipoff_utc)
       ) AS INTEGER) AS days_rest
FROM game g
JOIN team_game_stat s ON s.game_id = g.game_id
JOIN team_game_stat o ON o.game_id = g.game_id AND o.team_id = s.opp_team_id
WHERE g.status = 'closed';

-- Rolling form with NO LOOKAHEAD. The frame ends at the PRECEDING row, so a
-- row never sees its own result. This is the single most common bug in
-- backtest feature engineering and it belongs in the schema, not in each script.
CREATE VIEW v_team_form AS
SELECT *,
  AVG(margin) OVER w AS margin_l10,
  AVG(off_rating) OVER w AS ortg_l10,
  AVG(def_rating) OVER w AS drtg_l10,
  SUM(won)  OVER w AS wins_l10
FROM v_team_game
WINDOW w AS (PARTITION BY team_id, season_id ORDER BY tipoff_utc
             ROWS BETWEEN 10 PRECEDING AND 1 PRECEDING);

-- ------------------------------------------------------------ key player
CREATE VIEW v_player_impact AS
SELECT p.player_id, pl.full_name, p.team_id, g.season_id,
       COUNT(*) AS gp,
       AVG(p.pts) AS ppg,
       AVG(p.plus_minus) AS pm_per_g,
       SUM(p.pts) * 1.0 / NULLIF(SUM(t.pts),0) AS pts_share,
       AVG(p.ts_pct) AS ts_pct
FROM player_game_stat p
JOIN player pl ON pl.player_id = p.player_id
JOIN game g ON g.game_id = p.game_id
JOIN team_game_stat t ON t.game_id = p.game_id AND t.team_id = p.team_id
GROUP BY p.player_id, p.team_id, g.season_id;

-- ------------------------------------------------------------ replay
-- Point-in-time reconstruction. Given any elapsed_sec, returns the last known
-- state at or before it — the "rewind the game" primitive.
--   SELECT * FROM v_game_rewind WHERE game_id=? AND elapsed_sec <= 1440
--   ORDER BY elapsed_sec DESC LIMIT 1;
CREATE VIEW v_game_rewind AS
SELECT s.game_id, s.elapsed_sec, s.period, s.home_pts, s.away_pts, s.margin,
       s.frac_remaining, s.source,
       g.home_team_id, g.away_team_id,
       g.home_pts AS final_home, g.away_pts AS final_away,
       (g.home_pts - g.away_pts) - s.margin AS margin_still_to_come
FROM game_state s JOIN game g USING (game_id);

-- ------------------------------------------------------------ market
CREATE VIEW v_line_movement AS
SELECT game_id, market, side, book_id,
       MIN(observed_at) AS first_seen,
       MAX(observed_at) AS last_seen,
       COUNT(*) AS n_obs,
       (SELECT price_american FROM market_line m2
        WHERE m2.game_id=m.game_id AND m2.market=m.market AND m2.side=m.side
          AND m2.book_id=m.book_id ORDER BY observed_at ASC LIMIT 1) AS open_price,
       (SELECT price_american FROM market_line m3
        WHERE m3.game_id=m.game_id AND m3.market=m.market AND m3.side=m.side
          AND m3.book_id=m.book_id AND m3.is_closing=1) AS close_price
FROM market_line m
GROUP BY game_id, market, side, book_id;

CREATE VIEW v_clv_scorecard AS
SELECT b.model_version,
       COUNT(*) AS n_bets,
       SUM(gr.pnl) AS pnl,
       SUM(gr.pnl)/SUM(b.stake) AS roi,
       AVG(gr.clv_pct) AS avg_clv,
       AVG(gr.beat_close) AS beat_close_rate,
       SUM(b.stake * b.edge_est) AS expected_pnl
FROM bet b JOIN bet_grade gr USING (bet_id)
GROUP BY b.model_version;
