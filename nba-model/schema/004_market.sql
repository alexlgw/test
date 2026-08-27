-- 004_market.sql : lines, bets, grading
--
-- This is the half of the database the sports feed cannot fill. It is defined
-- first anyway, because the shape of these tables determines whether the
-- project can ever answer "was that a good bet" as opposed to "did it win".
--
-- The one rule that matters: a line is a TIME SERIES, not an attribute of a
-- game. `game.spread` would be a modelling error — the whole signal is in how
-- the number moved between open and close, and a single column destroys it.

PRAGMA foreign_keys = ON;

CREATE TABLE book (
    book_id       INTEGER PRIMARY KEY,
    code          TEXT NOT NULL UNIQUE,      -- 'pinnacle','draftkings','kalshi'
    display_name  TEXT NOT NULL,
    -- 'sharp' books are your fair-price anchor; 'soft' books are where you
    -- shop; 'exchange' has no vig and is priced differently. The model treats
    -- these three classes differently, so the class belongs in the schema.
    class         TEXT NOT NULL CHECK (class IN ('sharp','soft','exchange')),
    is_licensed_us INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE market_line (
    line_id       INTEGER PRIMARY KEY,
    game_id       TEXT    NOT NULL REFERENCES game(game_id) ON DELETE CASCADE,
    book_id       INTEGER NOT NULL REFERENCES book(book_id),
    market        TEXT    NOT NULL CHECK (market IN ('ml','spread','total','player_prop')),
    -- side is the selection: team_id for ml/spread, 'over'/'under' for total.
    -- Kept as TEXT rather than two nullable FK columns because the market types
    -- genuinely differ in what a "side" is.
    side          TEXT    NOT NULL,
    player_id     INTEGER REFERENCES player(player_id),   -- props only
    handicap      REAL,                      -- spread or total; NULL for ml
    price_american INTEGER NOT NULL,
    -- Stored so you never re-derive it inconsistently in five query sites.
    price_decimal REAL GENERATED ALWAYS AS (
        CASE WHEN price_american > 0 THEN price_american/100.0 + 1
             ELSE 100.0/ABS(price_american) + 1 END) VIRTUAL,
    implied_prob  REAL GENERATED ALWAYS AS (
        CASE WHEN price_american > 0 THEN 100.0/(price_american+100)
             ELSE ABS(price_american)*1.0/(ABS(price_american)+100) END) VIRTUAL,
    observed_at   TEXT    NOT NULL,
    -- is_closing is set by the ingest at tipoff, not inferred later by MAX().
    -- The last line you happened to SCRAPE is not the closing line; a poller
    -- that dies at 6pm would otherwise silently corrupt every CLV number.
    is_closing    INTEGER NOT NULL DEFAULT 0 CHECK (is_closing IN (0,1)),
    payload_id    INTEGER REFERENCES raw_payload(payload_id)
);
CREATE INDEX ix_line_lookup  ON market_line (game_id, market, book_id, observed_at);
CREATE UNIQUE INDEX ux_line_closing ON market_line (game_id, market, side, book_id)
    WHERE is_closing = 1;                    -- at most one close per selection

-- Devigged fair probability, computed per (game, market, book, timestamp) from
-- both sides of that market. Stored rather than recomputed because the METHOD
-- matters and must be recorded: multiplicative, power and Shin disagree by
-- enough to flip a marginal bet, as the earlier worked example showed.
CREATE TABLE fair_price (
    game_id       TEXT    NOT NULL REFERENCES game(game_id) ON DELETE CASCADE,
    book_id       INTEGER NOT NULL REFERENCES book(book_id),
    market        TEXT    NOT NULL,
    side          TEXT    NOT NULL,
    observed_at   TEXT    NOT NULL,
    method        TEXT    NOT NULL CHECK (method IN ('multiplicative','power','shin')),
    fair_prob     REAL    NOT NULL CHECK (fair_prob > 0 AND fair_prob < 1),
    overround     REAL    NOT NULL,
    PRIMARY KEY (game_id, book_id, market, side, observed_at, method)
);

-- ---------------------------------------------------------------- the ledger
CREATE TABLE bet (
    bet_id        INTEGER PRIMARY KEY,
    game_id       TEXT    NOT NULL REFERENCES game(game_id),
    book_id       INTEGER NOT NULL REFERENCES book(book_id),
    market        TEXT    NOT NULL,
    side          TEXT    NOT NULL,
    player_id     INTEGER REFERENCES player(player_id),
    handicap      REAL,
    price_american INTEGER NOT NULL,
    stake         REAL    NOT NULL CHECK (stake > 0),
    placed_at     TEXT    NOT NULL,
    -- What you believed AT THE TIME. Frozen. Never updated when the model is
    -- retrained, or every historical CLV number becomes retroactively fictional.
    model_fair_prob REAL,
    model_version TEXT,
    edge_est      REAL,
    kelly_frac    REAL,
    is_live       INTEGER NOT NULL DEFAULT 0 CHECK (is_live IN (0,1)),
    notes         TEXT
);
CREATE INDEX ix_bet_game ON bet (game_id, placed_at);

CREATE TABLE bet_grade (
    bet_id        INTEGER PRIMARY KEY REFERENCES bet(bet_id) ON DELETE CASCADE,
    result        TEXT    NOT NULL CHECK (result IN ('win','loss','push','void')),
    pnl           REAL    NOT NULL,
    -- CLV: the benchmark price and the resulting delta. This, not pnl, is the
    -- column you evaluate the operation on.
    close_price_american INTEGER,
    close_fair_prob REAL,
    clv_pct       REAL,                      -- (your_decimal / fair_decimal) - 1
    beat_close    INTEGER GENERATED ALWAYS AS (CASE WHEN clv_pct > 0 THEN 1 ELSE 0 END) VIRTUAL,
    graded_at     TEXT    NOT NULL
);
