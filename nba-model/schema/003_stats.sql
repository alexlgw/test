-- 003_stats.sql : box score facts
--
-- SCHEMA SHAPE DECISION (the important one in this file)
--
-- The feed returns ~70 team fields and ~40 player fields per game, and it OMITS
-- keys whose value is zero — a player with no free throws simply has no
-- free_throws_made key. Three options were considered:
--
--   (a) Wide table, one column per field.
--       Fast, typed, indexable. But a feed adding a field means ALTER TABLE,
--       and 70 mostly-null columns is a maintenance tax.
--   (b) EAV / long: (game_id, team_id, stat_key, value).
--       Survives any schema drift, but every real query becomes a pivot, and
--       you lose types and constraints entirely.
--   (c) HYBRID: type the ~25 fields you will actually filter, join and model
--       on; park the rest in a JSON column.
--
-- (c) is used here. SQLite ships JSON1, so the overflow stays queryable
-- (`extra->>'$.true_shooting_pct'`), and any field that later earns its keep
-- gets promoted to an indexed GENERATED column with no data migration and no
-- re-ingest. That promotion path is what makes the hybrid safe rather than lazy.
--
-- Omitted-key handling: NULL means "the feed did not report it", which for this
-- source means zero. That distinction is preserved rather than coalesced at
-- write time, because "0 attempts" and "not reported" diverge the moment a
-- second source is added.

PRAGMA foreign_keys = ON;

CREATE TABLE team_game_stat (
    game_id        TEXT    NOT NULL REFERENCES game(game_id) ON DELETE CASCADE,
    team_id        INTEGER NOT NULL REFERENCES team(team_id),
    opp_team_id    INTEGER NOT NULL REFERENCES team(team_id),
    is_home        INTEGER NOT NULL CHECK (is_home IN (0,1)),

    -- counting stats (typed core)
    pts            INTEGER,
    fgm            INTEGER, fga INTEGER,
    fg3m           INTEGER, fg3a INTEGER,
    ftm            INTEGER, fta INTEGER,
    oreb           INTEGER, dreb INTEGER,
    ast            INTEGER, stl INTEGER, blk INTEGER,
    tov            INTEGER, pf  INTEGER,

    -- pace/efficiency: the only fields that make cross-team comparison valid
    possessions    REAL,
    off_rating     REAL,
    def_rating     REAL,

    -- context stats that actually move lines
    pts_in_paint   INTEGER,
    fastbreak_pts  INTEGER,
    second_chance_pts INTEGER,
    bench_pts      INTEGER,
    biggest_lead   INTEGER,

    -- derived on read, never stored: a stored percentage is a second copy of
    -- the truth that can drift from its numerator and denominator.
    fg_pct         REAL GENERATED ALWAYS AS (CASE WHEN fga>0 THEN 1.0*fgm/fga END) VIRTUAL,
    fg3_pct        REAL GENERATED ALWAYS AS (CASE WHEN fg3a>0 THEN 1.0*fg3m/fg3a END) VIRTUAL,
    efg_pct        REAL GENERATED ALWAYS AS (CASE WHEN fga>0 THEN (fgm+0.5*fg3m)*1.0/fga END) VIRTUAL,
    ts_pct         REAL GENERATED ALWAYS AS (
                     CASE WHEN (fga+0.44*fta)>0 THEN pts/(2.0*(fga+0.44*fta)) END) VIRTUAL,
    reb            INTEGER GENERATED ALWAYS AS (COALESCE(oreb,0)+COALESCE(dreb,0)) VIRTUAL,

    extra          TEXT CHECK (extra IS NULL OR json_valid(extra)),
    payload_id     INTEGER REFERENCES raw_payload(payload_id),
    PRIMARY KEY (game_id, team_id)
);
CREATE INDEX ix_tgs_team ON team_game_stat (team_id, game_id);

CREATE TABLE player_game_stat (
    game_id        TEXT    NOT NULL REFERENCES game(game_id) ON DELETE CASCADE,
    player_id      INTEGER NOT NULL REFERENCES player(player_id),
    team_id        INTEGER NOT NULL REFERENCES team(team_id),
    position       TEXT,
    started        INTEGER CHECK (started IN (0,1)),

    -- KNOWN GAP: the current feed does not return minutes played. Every rate
    -- stat and every usage model needs it. The column is defined so the shape
    -- is right, and stays NULL until a source that carries it is wired in.
    -- Do not silently substitute possessions or plus/minus for it.
    minutes        REAL,

    pts            INTEGER,
    fgm INTEGER, fga INTEGER, fg3m INTEGER, fg3a INTEGER, ftm INTEGER, fta INTEGER,
    oreb INTEGER, dreb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER,
    tov INTEGER, pf INTEGER,
    plus_minus     INTEGER,
    off_rating     REAL,
    def_rating     REAL,
    usage_pct      REAL,

    reb            INTEGER GENERATED ALWAYS AS (COALESCE(oreb,0)+COALESCE(dreb,0)) VIRTUAL,
    ts_pct         REAL GENERATED ALWAYS AS (
                     CASE WHEN (fga+0.44*fta)>0 THEN pts/(2.0*(fga+0.44*fta)) END) VIRTUAL,

    extra          TEXT CHECK (extra IS NULL OR json_valid(extra)),
    payload_id     INTEGER REFERENCES raw_payload(payload_id),
    PRIMARY KEY (game_id, player_id)
);
CREATE INDEX ix_pgs_player ON player_game_stat (player_id, game_id);
CREATE INDEX ix_pgs_team   ON player_game_stat (team_id, game_id);

-- ------------------------------------------------------------- "key player"
-- Deliberately NOT a boolean on `player`. Who matters is a property of a
-- (player, team, season) window and it changes over the year, so it is stored
-- as a scored role with the inputs kept alongside the label. That way a
-- disagreement is debuggable instead of being an opinion baked into a flag.
CREATE TABLE player_season_role (
    player_id      INTEGER NOT NULL REFERENCES player(player_id),
    team_id        INTEGER NOT NULL REFERENCES team(team_id),
    season_id      INTEGER NOT NULL REFERENCES season(season_id),
    as_of_date     TEXT    NOT NULL,         -- roles are point-in-time
    games_played   INTEGER NOT NULL,
    pts_share      REAL,                     -- share of team points
    usage_share    REAL,
    plusminus_per_g REAL,
    role           TEXT CHECK (role IN ('franchise','starter','rotation','fringe')),
    role_score     REAL,
    PRIMARY KEY (player_id, team_id, season_id, as_of_date)
);
