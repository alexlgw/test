-- 002_games.sql : games and the replay substrate
--
-- "Turn games back" is an event-sourcing problem. The rule that makes it work:
--   game_event  = immutable append-only log (what happened)
--   game_state  = derived, rebuildable, disposable (what was true at time T)
-- If you can DELETE every row of game_state and regenerate it from game_event,
-- the design is correct. If you can't, state has become the source of truth
-- and rewind will drift.

PRAGMA foreign_keys = ON;

CREATE TABLE game (
    game_id       TEXT    PRIMARY KEY,       -- feed UUID, kept as-is
    season_id     INTEGER NOT NULL REFERENCES season(season_id),
    phase_id      INTEGER NOT NULL REFERENCES season_phase(phase_id),
    home_team_id  INTEGER NOT NULL REFERENCES team(team_id),
    away_team_id  INTEGER NOT NULL REFERENCES team(team_id),
    tipoff_utc    TEXT    NOT NULL,
    status        TEXT    NOT NULL CHECK (status IN ('scheduled','inprogress','closed','postponed')),
    -- Final score is DENORMALIZED here on purpose: it is queried constantly and
    -- is stable once status='closed'. It must equal the sum of game_period_score;
    -- 005_derived.sql ships a check view that asserts this.
    home_pts      INTEGER,
    away_pts      INTEGER,
    n_periods     INTEGER,                   -- 4, or 5+ for OT
    series_label  TEXT,                      -- 'Game 7' for playoff games
    payload_id    INTEGER REFERENCES raw_payload(payload_id),
    CHECK (home_team_id <> away_team_id),
    CHECK (status <> 'closed' OR (home_pts IS NOT NULL AND away_pts IS NOT NULL))
);
CREATE INDEX ix_game_date ON game (tipoff_utc);
CREATE INDEX ix_game_home ON game (home_team_id, tipoff_utc);
CREATE INDEX ix_game_away ON game (away_team_id, tipoff_utc);

-- Period-level scoring. This IS available from the current feed
-- (scoring_by_period), unlike play-by-play, which is not.
CREATE TABLE game_period_score (
    game_id       TEXT    NOT NULL REFERENCES game(game_id) ON DELETE CASCADE,
    period        INTEGER NOT NULL,          -- 1..4, 5+ = OT
    team_id       INTEGER NOT NULL REFERENCES team(team_id),
    points        INTEGER NOT NULL,
    PRIMARY KEY (game_id, period, team_id)
);

-- ------------------------------------------------------------ the event log
-- APPEND ONLY. No UPDATE, no DELETE (outside of a full game re-ingest).
-- Currently unpopulated: the feed does not expose play-by-play. The table
-- exists now so that adding a PBP source later is an INSERT, not a migration.
CREATE TABLE game_event (
    game_id       TEXT    NOT NULL REFERENCES game(game_id) ON DELETE CASCADE,
    seq           INTEGER NOT NULL,          -- monotonic within game, from 1
    period        INTEGER NOT NULL,
    -- Clock stored as SECONDS ELAPSED from tipoff, never as the displayed
    -- "9:47 remaining" string. Elapsed is monotonic across periods and OT,
    -- which makes ORDER BY and time-window joins trivial. Display format is a
    -- presentation concern, computed on the way out.
    elapsed_sec   INTEGER NOT NULL,
    event_type    TEXT    NOT NULL,          -- 'shot','rebound','foul','sub',...
    team_id       INTEGER REFERENCES team(team_id),
    player_id     INTEGER REFERENCES player(player_id),
    -- Running score AFTER this event. Redundant with a fold over prior events,
    -- but storing it makes point-in-time queries O(1) instead of O(n) and lets
    -- you validate the fold. Cheap insurance.
    home_pts      INTEGER NOT NULL,
    away_pts      INTEGER NOT NULL,
    detail        TEXT,                      -- JSON: shot coords, assist, etc.
    payload_id    INTEGER REFERENCES raw_payload(payload_id),
    PRIMARY KEY (game_id, seq)
);
CREATE INDEX ix_event_time   ON game_event (game_id, elapsed_sec);
CREATE INDEX ix_event_player ON game_event (player_id, game_id);

-- ------------------------------------------------------ derived, rebuildable
-- Materialized point-in-time states. Every row is reproducible from the log
-- (or, today, from game_period_score). `source` records which, so you can tell
-- a coarse period-boundary snapshot from a true event-derived one.
CREATE TABLE game_state (
    game_id       TEXT    NOT NULL REFERENCES game(game_id) ON DELETE CASCADE,
    elapsed_sec   INTEGER NOT NULL,
    period        INTEGER NOT NULL,
    home_pts      INTEGER NOT NULL,
    away_pts      INTEGER NOT NULL,
    margin        INTEGER GENERATED ALWAYS AS (home_pts - away_pts) VIRTUAL,
    frac_remaining REAL   NOT NULL,          -- 1.0 at tip, 0.0 at final buzzer
    source        TEXT    NOT NULL CHECK (source IN ('period_boundary','event','interpolated')),
    PRIMARY KEY (game_id, elapsed_sec)
);
CREATE INDEX ix_state_margin ON game_state (game_id, period, margin);

-- Availability. Injuries/rest are the largest single driver of line movement,
-- and they are point-in-time facts: what mattered is what was KNOWN at tipoff,
-- not what was true afterward. Hence known_at, and no overwriting.
CREATE TABLE player_availability (
    game_id       TEXT    NOT NULL REFERENCES game(game_id) ON DELETE CASCADE,
    player_id     INTEGER NOT NULL REFERENCES player(player_id),
    status        TEXT    NOT NULL CHECK (status IN ('active','out','questionable','doubtful','probable','dnp')),
    reason        TEXT,
    known_at      TEXT    NOT NULL,
    PRIMARY KEY (game_id, player_id, known_at)
);
