# nba-model

An NBA statistics database and betting-analysis toolkit built around a
principle: **store what actually happened, derive everything else.** Raw feed
payloads are the source of truth, facts are parsed out of them deterministically,
and any figure that can be computed (percentages, replay state, key-player
ranking) is a view or a generated column — never a second copy that can drift.

The database currently models two teams (Boston Celtics and Oklahoma City
Thunder) loaded from one real 2025-26 game (BOS 119, OKC 109, March 25),
with a schema designed to scale to the full league.

## Quick start

```bash
# The core database (schema, ingest, verify) needs no third-party packages —
# it runs on the Python standard library.
make rebuild        # clean DB, run migrations, load the real game, then verify
```

`make rebuild` runs `clean`, then `init` (`scripts/bootstrap.py` — build +
ingest), then `verify` (`scripts/verify.py`), which demonstrates game replay,
the integrity checks, the generated columns, JSON overflow, and the derived
key-player view. Requires Python 3.9+ (uses SQLite generated columns and the
JSON1 extension, both built into CPython).

`requirements.txt` (`numpy`, `pandas`, `pytest`) covers the exploratory
backtest in `research/` and the `make test` target; the core rebuild needs
none of them.

## Repository layout

```
schema/           Migrations, applied in order by the runner
  001_core.sql      seasons, teams, players, identity resolution
  002_games.sql     games, period scores, event/snapshot replay model
  003_stats.sql     stat facts (typed core columns + JSON overflow)
  004_market.sql    odds as a time series, bet ledger, CLV
  005_derived.sql   integrity-check + team-form + key-player views
src/nbadb/
  db.py             connection, migration runner, identity resolution
  ingest/feed.py    parse raw feed JSON into the schema; replay state
scripts/
  bootstrap.py      create the DB and load the real BOS/OKC game
  verify.py         prove replay, integrity, and derived views work
data/
  bos_okc_raw.json  the real feed payload, committed as a fixture
research/
  backtest.py       pattern-mining walkthrough on two teams (see note below)
simulator/
  clv-desk.html     paper-betting simulator with CLV grading
  clv-desk-live.html   the simulator with in-play betting windows
```

The database file (`data/nba.db`) is a build artifact and is not committed —
it is fully rebuildable from the fixture with `make rebuild`.

## The design decisions that matter

1. **Raw payloads are the source of truth.** Every response lands in
   `raw_payload` verbatim, content-addressed by SHA-256. Re-fetching identical
   content is a no-op; *changed* content for the same key inserts a new row, so
   silent box-score revisions become visible instead of overwriting history.
   Every fact row carries a `payload_id` back to the JSON it came from.

2. **Event log vs. derived state.** `game_event` is append-only; `game_state`
   is disposable and must be exactly rebuildable from the events. The clock is
   stored as **elapsed seconds from tipoff**, never as "time remaining" —
   elapsed is monotonic across overtime, so ordering and time-window joins stay
   trivial. This is what lets you rewind a game to any moment and read
   `margin_still_to_come` — the column a live-betting model trains on.

3. **Hybrid stats table.** The ~25 fields you actually filter and model on are
   typed columns; the rest are parked in a queryable JSON column
   (`extra->>'$.points_off_turnovers'`). When a field earns its keep it gets
   promoted to a generated column with no re-ingest.

4. **Percentages are never stored.** `efg_pct`, `ts_pct`, `reb` and friends are
   `GENERATED ALWAYS ... VIRTUAL`. There is only one copy of the truth, so they
   cannot drift from the raw counts.

5. **Lines are a time series.** All the signal is in the movement between open
   and close, so `market_line` is keyed by `observed_at`, with `is_closing` set
   at tipoff by the ingest — never inferred with `MAX()`, which a dead poller
   would corrupt silently.

6. **Player identity is resolved, not guessed.** `player_alias` maps observed
   name strings to a `player_id` with diacritic normalization. Ambiguous names
   are parked as `unresolved` rather than minting a duplicate player.

## What is intentionally empty

`game_event`, `market_line`, `fair_price`, `bet`, and `player_availability` are
schema-complete and empty. Filling them is an `INSERT`, not a migration. The two
real data gaps are **play-by-play** (this feed carries none) and **historical
odds** (needs a paid archive endpoint such as SportsGameOdds or OddsPapi). The
`minutes` column is defined and stays `NULL` — the feed omits it, and nothing is
substituted, because every rate/usage stat depends on it.

The integrity checks surface these gaps rather than hiding them: on the loaded
game, `check_boxscore_reconciliation` flags that the feed truncated the roster
(8–9 players returned for a 12+ player game), leaving ~a quarter of the scoring
unattributed.

## About `research/backtest.py`

This is the honest walkthrough that motivated the database, not a strategy to
run. It mines 24 patterns on a two-team sample, watches the best one ("Road
games", 59.6% ATS) survive a holdout, and then kills it: a best-of-24 search
over pure coin-flips beats that number ~79% of the time, and regenerating 40
seasons collapses it to 48.9% ATS. The takeaway is that 164 games cannot
distinguish a 55% bettor from a coin, and the only thing that survives is
**shopping price against a sharp fair line** (CLV) — a property of the
transaction, not of any basketball pattern. It needs `numpy` and `pandas`
(`pip install -r requirements.txt`).

## Provenance

This project was originally built inside a single Claude conversation (the
sandbox could hand over individual files but not a `.git` directory) and has
been migrated here as a real repository.
