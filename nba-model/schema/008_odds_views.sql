-- 008_odds_views.sql : read helpers over market_line (real ESPN odds)
--
-- Storage already exists (market_line in 004). This migration only adds views
-- that pivot the closing line into one row per game and grade the two teams
-- against it, so the analysis layer reads a clean table instead of repeating
-- the same correlated subqueries. Nothing here is stored; it is all derived
-- from market_line + the game result, so it can never drift from either.

PRAGMA foreign_keys = ON;

-- One row per game: the closing spread (from the HOME team's perspective), the
-- closing total, and both moneylines. Handy anchor for CLV and grading.
CREATE VIEW v_closing_line AS
SELECT g.game_id, g.tipoff_utc, ht.abbrev AS home, at.abbrev AS away,
       g.home_pts, g.away_pts,
       (g.home_pts + g.away_pts) AS total_pts,
       (SELECT handicap FROM market_line m WHERE m.game_id=g.game_id
          AND m.market='spread' AND m.side=CAST(g.home_team_id AS TEXT)
          AND m.is_closing=1) AS home_spread_close,
       (SELECT handicap FROM market_line m WHERE m.game_id=g.game_id
          AND m.market='total' AND m.side='over' AND m.is_closing=1) AS total_close,
       (SELECT price_american FROM market_line m WHERE m.game_id=g.game_id
          AND m.market='ml' AND m.side=CAST(g.home_team_id AS TEXT)
          AND m.is_closing=1) AS home_ml_close,
       (SELECT price_american FROM market_line m WHERE m.game_id=g.game_id
          AND m.market='ml' AND m.side=CAST(g.away_team_id AS TEXT)
          AND m.is_closing=1) AS away_ml_close
FROM game g
JOIN team ht ON ht.team_id=g.home_team_id
JOIN team at ON at.team_id=g.away_team_id
WHERE g.season_id=2025 AND g.home_pts IS NOT NULL;

-- Per-game, per-team grading against the CLOSING line: straight-up result, the
-- team's margin vs the spread it was given (cover = margin + spread > 0), and
-- the game total vs the closing total (over/under/push).
CREATE VIEW v_team_result_vs_line AS
SELECT cl.game_id, cl.tipoff_utc, t.abbrev,
       CASE WHEN t.abbrev=cl.home THEN 1 ELSE 0 END AS is_home,
       CASE WHEN t.abbrev=cl.home THEN cl.home_pts ELSE cl.away_pts END AS pts,
       CASE WHEN t.abbrev=cl.home THEN cl.away_pts ELSE cl.home_pts END AS opp_pts,
       CASE WHEN t.abbrev=cl.home THEN cl.home_spread_close
            ELSE -cl.home_spread_close END AS team_spread_close,
       CASE WHEN t.abbrev=cl.home THEN cl.home_ml_close ELSE cl.away_ml_close END AS team_ml_close,
       cl.total_close, cl.total_pts,
       CASE WHEN (CASE WHEN t.abbrev=cl.home THEN cl.home_pts ELSE cl.away_pts END) >
                 (CASE WHEN t.abbrev=cl.home THEN cl.away_pts ELSE cl.home_pts END)
            THEN 1 ELSE 0 END AS won
FROM v_closing_line cl
JOIN team t ON t.abbrev IN (cl.home, cl.away);
