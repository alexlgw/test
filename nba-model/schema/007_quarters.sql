-- 007_quarters.sql : per-quarter scoring (real ESPN data)
--
-- Team scoring by quarter already fits game_period_score (002) -- that table was
-- built for exactly this and is now filled with a real season instead of one
-- game. What it could NOT hold is PLAYER scoring by quarter, because that needs
-- play-by-play. ESPN's scoring plays carry (period, scorer, points), so this
-- migration adds the player-per-quarter table they populate.
--
-- SCOPE HONESTY: a row exists only for a (player, game, quarter) in which the
-- player SCORED -- scoring plays are the only per-quarter signal the feed gives.
-- So SUM(pts) is exact, but a per-game average must divide by games PLAYED
-- (from player_game_stat), not by the number of rows here, or quarters with
-- zero points silently vanish from the denominator. The analysis script does
-- exactly that; the view below only aggregates, it does not average per game.

PRAGMA foreign_keys = ON;

CREATE TABLE player_period_stat (
    game_id    TEXT    NOT NULL REFERENCES game(game_id) ON DELETE CASCADE,
    player_id  INTEGER NOT NULL REFERENCES player(player_id),
    team_id    INTEGER NOT NULL REFERENCES team(team_id),
    period     INTEGER NOT NULL,               -- 1-4 regulation, 5+ = OT
    pts   INTEGER NOT NULL DEFAULT 0,
    fgm   INTEGER NOT NULL DEFAULT 0,          -- made field goals (2s and 3s)
    fg3m  INTEGER NOT NULL DEFAULT 0,
    ftm   INTEGER NOT NULL DEFAULT 0,
    payload_id INTEGER REFERENCES raw_payload(payload_id),
    PRIMARY KEY (game_id, player_id, period)
);
CREATE INDEX ix_pps_player ON player_period_stat (player_id, period);
CREATE INDEX ix_pps_team   ON player_period_stat (team_id, period);

-- Team scoring by quarter, split by result and venue. Regulation quarters only
-- (OT is not a fixed 12 minutes, so it does not belong in a per-quarter mean).
CREATE VIEW v_team_quarter_scoring AS
SELECT t.abbrev, gps.period,
       COUNT(*) AS games,
       ROUND(AVG(gps.points), 2) AS avg_pts,
       ROUND(AVG(CASE WHEN (gps.team_id=g.home_team_id AND g.home_pts>g.away_pts)
                        OR (gps.team_id=g.away_team_id AND g.away_pts>g.home_pts)
                     THEN gps.points END), 2) AS avg_in_wins,
       ROUND(AVG(CASE WHEN (gps.team_id=g.home_team_id AND g.home_pts<g.away_pts)
                        OR (gps.team_id=g.away_team_id AND g.away_pts<g.home_pts)
                     THEN gps.points END), 2) AS avg_in_losses,
       ROUND(AVG(CASE WHEN gps.team_id=g.home_team_id THEN gps.points END), 2) AS avg_home,
       ROUND(AVG(CASE WHEN gps.team_id=g.away_team_id THEN gps.points END), 2) AS avg_away
FROM game_period_score gps
JOIN game g ON g.game_id = gps.game_id
JOIN team t ON t.team_id = gps.team_id
WHERE gps.period BETWEEN 1 AND 4
GROUP BY t.abbrev, gps.period;

-- Player quarter totals (regulation). Averages are computed per games-played in
-- the analysis layer, per the scope note above -- this view sums, on purpose.
CREATE VIEW v_player_quarter_scoring AS
SELECT p.full_name, t.abbrev, pps.period,
       COUNT(*)      AS scoring_games,   -- games the player scored in this quarter
       SUM(pps.pts)  AS total_pts,
       SUM(pps.fg3m) AS total_3pm
FROM player_period_stat pps
JOIN player p USING (player_id)
JOIN team   t USING (team_id)
WHERE pps.period BETWEEN 1 AND 4
GROUP BY p.full_name, t.abbrev, pps.period;
