-- 001_core.sql : dimensions and identity
-- Design rule: nothing in here is derived. These tables answer "who/what",
-- never "how many". Facts live in 003_stats.sql.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- provenance
-- Every fetched payload lands here verbatim, before parsing. Nothing else in
-- the database is trusted more than this table. If a parse is wrong, you
-- re-run it against these rows instead of re-fetching (feeds mutate silently).
CREATE TABLE raw_payload (
    payload_id    INTEGER PRIMARY KEY,
    source        TEXT    NOT NULL,          -- 'sportradar_feed', 'oddsapi', ...
    endpoint      TEXT    NOT NULL,          -- 'game_stats', 'scores'
    request_key   TEXT    NOT NULL,          -- game_id / team / date queried
    body          TEXT    NOT NULL,          -- raw JSON, untouched
    body_sha256   TEXT    NOT NULL,
    fetched_at    TEXT    NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
    UNIQUE (source, endpoint, request_key, body_sha256)
);
-- The UNIQUE above is deliberate: re-fetching identical content is a no-op,
-- but a CHANGED body for the same key inserts a NEW row. Feed corrections
-- (stat revisions, scoring changes) become visible instead of overwriting.
CREATE INDEX ix_raw_key ON raw_payload (source, endpoint, request_key, fetched_at DESC);

-- ---------------------------------------------------------------- seasons
CREATE TABLE season (
    season_id     INTEGER PRIMARY KEY,       -- 2025 = the 2025-26 season
    label         TEXT    NOT NULL UNIQUE,   -- '2025-26'
    start_date    TEXT,
    end_date      TEXT
);

CREATE TABLE season_phase (
    phase_id      INTEGER PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE       -- 'PRE','REG','PLAYIN','PLAYOFF'
);

-- ---------------------------------------------------------------- teams
-- Franchise is permanent; team_season carries anything that can change
-- (name, conference, coach). Never put a mutable attribute on `team`.
CREATE TABLE team (
    team_id       INTEGER PRIMARY KEY,
    abbrev        TEXT    NOT NULL UNIQUE,   -- 'BOS' — the feed's join key
    franchise_key TEXT    NOT NULL           -- stable across relocation/rename
);

CREATE TABLE team_season (
    team_id       INTEGER NOT NULL REFERENCES team(team_id),
    season_id     INTEGER NOT NULL REFERENCES season(season_id),
    market        TEXT,                      -- 'Boston'
    name          TEXT,                      -- 'Celtics'
    conference    TEXT CHECK (conference IN ('East','West')),
    division      TEXT,
    PRIMARY KEY (team_id, season_id)
);

-- ---------------------------------------------------------------- players
-- The feed gives NAMES ONLY, no stable player id. That is the single biggest
-- data-quality hazard in this project, so identity gets its own machinery.
CREATE TABLE player (
    player_id     INTEGER PRIMARY KEY,
    full_name     TEXT    NOT NULL,
    birth_date    TEXT,                      -- the only reliable disambiguator
    primary_pos   TEXT,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ','now'))
);

-- Observed name strings -> resolved player. Feeds spell people differently
-- ('L. Doncic', 'Luka Doncic', 'Luka Dončić'). Unresolved strings are PARKED
-- here rather than silently minting a duplicate player row.
CREATE TABLE player_alias (
    alias_id      INTEGER PRIMARY KEY,
    source        TEXT    NOT NULL,
    observed_name TEXT    NOT NULL,
    norm_name     TEXT    NOT NULL,          -- casefold + strip diacritics
    player_id     INTEGER REFERENCES player(player_id),
    status        TEXT    NOT NULL DEFAULT 'unresolved'
                  CHECK (status IN ('resolved','unresolved','ambiguous')),
    resolved_at   TEXT,
    UNIQUE (source, observed_name)
);
CREATE INDEX ix_alias_norm ON player_alias (norm_name);
CREATE INDEX ix_alias_status ON player_alias (status) WHERE status <> 'resolved';

-- A player's time on a roster. Trades mean a player has MULTIPLE stints in one
-- season, so team membership can never be a column on `player`.
CREATE TABLE player_stint (
    stint_id      INTEGER PRIMARY KEY,
    player_id     INTEGER NOT NULL REFERENCES player(player_id),
    team_id       INTEGER NOT NULL REFERENCES team(team_id),
    season_id     INTEGER NOT NULL REFERENCES season(season_id),
    start_date    TEXT    NOT NULL,
    end_date      TEXT,                      -- NULL = current
    jersey        TEXT,
    CHECK (end_date IS NULL OR end_date >= start_date)
);
CREATE INDEX ix_stint_player ON player_stint (player_id, season_id);
CREATE INDEX ix_stint_team   ON player_stint (team_id, season_id, start_date);
