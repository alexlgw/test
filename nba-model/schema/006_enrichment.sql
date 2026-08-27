-- 006_enrichment.sql : season-level context from external reference sources
--
-- WHY THIS FILE EXISTS
-- The box-score facts in 003 describe individual GAMES. To judge the
-- probability of a future result you need SEASON-LEVEL priors: how good each
-- team actually is (efficiency, not just W-L), how they split home vs away, at
-- what pace they play, and which key players were actually available. That
-- signal is not in any single game_stats payload -- it is aggregated and
-- published by reference sources (Basketball-Reference, Wikipedia, StatMuse).
-- This migration adds tables to hold that enrichment.
--
-- PROVENANCE RULE (unchanged from the rest of the DB)
-- These rows are NOT the sandbox game feed. They come from cited public
-- sources, are landed verbatim in raw_payload with source='web_reference', and
-- every row carries payload_id back to that raw row PLUS an as_of_date --
-- because a season aggregate is only true as of a date. Percentages and net
-- values are GENERATED, never stored: one copy of the truth, same as 003.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------- team strength
-- Season aggregate strength + schedule split, one row per (team, season, date).
CREATE TABLE team_season_stat (
    team_id      INTEGER NOT NULL REFERENCES team(team_id),
    season_id    INTEGER NOT NULL REFERENCES season(season_id),
    as_of_date   TEXT    NOT NULL,            -- aggregates are point-in-time

    games        INTEGER NOT NULL,
    wins         INTEGER NOT NULL,
    losses       INTEGER NOT NULL,
    home_wins    INTEGER, home_losses INTEGER,
    away_wins    INTEGER, away_losses INTEGER,

    -- per-100-possession efficiency: the only basis on which two teams that
    -- played different schedules can be compared fairly.
    off_rating   REAL,
    def_rating   REAL,
    pace         REAL,                         -- possessions/48; scales totals
    srs          REAL,                         -- simple rating system (pt diff + SOS)

    conference   TEXT CHECK (conference IN ('East','West')),
    conf_rank    INTEGER,

    -- derived on read
    win_pct      REAL GENERATED ALWAYS AS (CASE WHEN games>0 THEN 1.0*wins/games END) VIRTUAL,
    net_rating   REAL GENERATED ALWAYS AS (off_rating - def_rating) VIRTUAL,
    home_win_pct REAL GENERATED ALWAYS AS (
                   CASE WHEN (home_wins+home_losses)>0
                        THEN 1.0*home_wins/(home_wins+home_losses) END) VIRTUAL,
    away_win_pct REAL GENERATED ALWAYS AS (
                   CASE WHEN (away_wins+away_losses)>0
                        THEN 1.0*away_wins/(away_wins+away_losses) END) VIRTUAL,

    source       TEXT NOT NULL,
    source_url   TEXT,
    payload_id   INTEGER REFERENCES raw_payload(payload_id),
    PRIMARY KEY (team_id, season_id, as_of_date),
    CHECK (wins + losses = games)
);

-- ---------------------------------------------------------- player context
-- Season per-game averages + availability, one row per (player, team, season, date).
CREATE TABLE player_season_stat (
    player_id     INTEGER NOT NULL REFERENCES player(player_id),
    team_id       INTEGER NOT NULL REFERENCES team(team_id),
    season_id     INTEGER NOT NULL REFERENCES season(season_id),
    as_of_date    TEXT    NOT NULL,

    games_played  INTEGER,
    team_games    INTEGER,                     -- games the TEAM played, for availability
    min_pg        REAL,
    pts_pg        REAL, reb_pg REAL, ast_pg REAL,
    fg_pct        REAL, fg3_pct REAL, ts_pct REAL,   -- stored as FRACTIONS (0.477)

    is_key_player INTEGER CHECK (is_key_player IN (0,1)) DEFAULT 0,
    avail_note    TEXT,                         -- 'returned from Achilles; 16 GP'

    -- fraction of the team's games this player was available for. A 31-ppg
    -- scorer at 55% availability is a very different prior than one at 95%,
    -- and a season average alone hides that.
    avail_rate    REAL GENERATED ALWAYS AS (
                    CASE WHEN team_games>0 THEN 1.0*games_played/team_games END) VIRTUAL,

    source        TEXT NOT NULL,
    source_url    TEXT,
    payload_id    INTEGER REFERENCES raw_payload(payload_id),
    PRIMARY KEY (player_id, team_id, season_id, as_of_date)
);
CREATE INDEX ix_pss_team ON player_season_stat (team_id, season_id);

-- ------------------------------------------------------- convenience views
-- One-line strength card per team-season: what a matchup model reads first.
CREATE VIEW v_team_strength AS
SELECT ts.team_id, t.abbrev, ts.season_id, ts.as_of_date,
       ts.wins, ts.losses, ts.win_pct,
       ts.off_rating, ts.def_rating, ts.net_rating, ts.pace,
       ts.home_win_pct, ts.away_win_pct, ts.conference, ts.conf_rank
FROM team_season_stat ts JOIN team t USING (team_id);

-- Key players and how available they actually were -- the injury context that
-- a bare season average buries.
CREATE VIEW v_key_player_availability AS
SELECT p.full_name, t.abbrev, ps.season_id,
       ps.games_played, ps.team_games, ps.avail_rate,
       ps.pts_pg, ps.reb_pg, ps.ast_pg, ps.ts_pct, ps.avail_note
FROM player_season_stat ps
JOIN player p USING (player_id)
JOIN team   t USING (team_id)
WHERE ps.is_key_player = 1
ORDER BY t.abbrev, ps.pts_pg DESC;
