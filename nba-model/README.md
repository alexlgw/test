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
  006_enrichment.sql season-level team strength + player availability (see below)
  007_quarters.sql  per-quarter player scoring + quarter-distribution views
  008_odds_views.sql closing-line + result-vs-line views over market_line
src/nbadb/
  db.py             connection, migration runner, identity resolution
  ingest/feed.py    parse raw feed JSON into the schema; replay state
  ingest/reference.py  parse season enrichment JSON (team strength, players)
  ingest/espn.py    parse the real ESPN season fixture (offline)
  ingest/odds.py    parse the ESPN odds fixture into market_line (offline)
scripts/
  bootstrap.py      create the DB and load the real BOS/OKC game
  enrich.py         load the season enrichment for BOS and OKC
  fetch_espn.py     NETWORK: refresh the games fixture
  fetch_odds.py     NETWORK: refresh the odds fixture (open+close lines)
  load_espn.py      load the real ESPN season into the DB (offline)
  load_odds.py      load the odds into market_line (offline)
  verify.py         prove replay, integrity, and derived views work
  matchup.py        win-probability estimate from the enriched data
  quarters.py       quarter-by-quarter scoring, team and per-player
  walkforward.py    sequential bet test (assumed -110 pricing)
  odds.py           grade the season at REAL closing lines + CLV
  strategies.py     test a menu of strategies + noise & out-of-sample guards
  edges.py          devig -> fair_price, market consistency, CLV ledger
src/nbadb/model/
  prob.py           odds conversion, two-way devig, spread->win-prob
data/
  bos_okc_raw.json  the real feed payload, committed as a fixture
  enrichment_2025_26.json  cited season aggregates for BOS and OKC
  espn_2025_26_games.json  real 162-game season (quarters, box, scorers)
  espn_odds_2025_26.json  real open+close lines (spread, ML, total) per game
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

## Season enrichment (`schema/006`, `data/enrichment_2025_26.json`)

A single game's box score cannot tell you who is likely to win the *next* game.
Judging that probability needs season-level priors, so the enrichment layer adds
two tables for the 2025-26 season of the two modelled teams:

- **`team_season_stat`** — record, home/away split, offensive & defensive
  rating, pace, and derived `net_rating` / `win_pct`. This is the basis on which
  two teams that played different schedules can be compared.
- **`player_season_stat`** — per-game averages plus **availability**
  (`games_played / team_games`), because a star who played 20% of the season
  inflates a team's season rating relative to who will actually be on the floor.

The data comes from cited public sources (Wikipedia, StatMuse, Sports
Illustrated — see the `sources` block in the JSON), and follows the same
provenance rule as the game feed: each row is landed verbatim in `raw_payload`
with `source='web_reference'` and carries an `as_of_date`, because a season
aggregate is only true as of a date. Load it with `make enrich`.

Two convenience views sit on top: `v_team_strength` (a one-line strength card
per team) and `v_key_player_availability` (key players with their availability
caveats).

`scripts/matchup.py` (`make matchup`, or `python3 scripts/matchup.py OKC BOS`)
turns this into a transparent win-probability estimate:

```
expected_margin = (home.net_rating - away.net_rating) + home_court(2.5)
win_prob(home)  = Phi(expected_margin / margin_sd(12))
```

For OKC (home) vs BOS it prints ~68% / 32% and a fair moneyline, then lists each
team's key players with availability flags — so the injury context (Tatum at
20%, Jalen Williams at 40%) is read *with* the estimate, not buried under it.
This is a season-strength prior, not a bet: to grade a wager you still need the
market line (`market_line` / `fair_price` in `004`), which needs a paid odds feed.

## Quarter data and the sequential bet test (`schema/007`, ESPN season)

`make rebuild` also loads a **real 162-game 2025-26 season** for BOS and OKC,
pulled from ESPN's public API (`scripts/fetch_espn.py` writes the committed
fixture `data/espn_2025_26_games.json`; `scripts/load_espn.py` ingests it
offline). Unlike the sandbox feed, this carries **minutes**, per-quarter team
linescores, and **per-quarter player points** parsed from play-by-play scoring
plays. It lands in the existing `game` / `game_period_score` / `player_game_stat`
tables plus the new `player_period_stat`.

- **`make quarters`** — how each team's scoring distributes across quarters
  (average, in wins vs losses, home vs away) and how each key player scores by
  quarter. Real findings for 2025-26: both teams' **2nd quarter** separates
  their wins from losses most (OKC +6.2, BOS +5.8 pts), and SGA is a **3rd-
  quarter** monster (11.1 pts/game in Q3 alone).

- **`make walkforward`** — the sequential test you asked for: bet game 1, use
  the result to inform game 2, and so on, with **no lookahead**. An adaptive
  strategy follows whichever simple rule ("ride the streak", "bounce back after
  a loss", "bet after a Q3 win", …) has the best record *so far*.

### The "$500 last season" answer

Betting OKC and BOS to win went **121-45 (72.9%)** — and that is exactly why it
is *not* a betting edge. These were 64- and 56-win teams; "bet them to win"
hitting ~73% is a tautology, not a pattern. Winning 73% only profits if you are
paid better than a 73% chance, i.e. better than ≈ **-269**. At the fantasy price
of -110 the sim prints ~+$196 on $500, but that number is an artifact of
underpricing a favorite. **At the real moneyline for a 73% winner, the same
record returns ≈ $0 before vig and a small loss after it.**

So, honestly: with $500 on these patterns last season you win **roughly
nothing**. The hit rate is real; the profit is not, because the sim prices bets
at an assumed -110 instead of the **actual closing lines the project still
doesn't have**. A genuine edge means beating that closing line (CLV) — which
needs a historical-odds feed, not more box-score or quarter data. The quarter
data is genuinely useful for *understanding* games and for quarter-level props;
it does not, by itself, manufacture a profitable system.

## Odds analysis — real closing lines (`schema/004` + `008`, `make odds`)

The wall this project kept hitting was odds: without real prices, no bet can be
graded in dollars. ESPN's core API turns out to carry **opening and closing
lines** (spread, moneyline, total) per game. `scripts/fetch_odds.py` pulls them
into the committed fixture `data/espn_odds_2025_26.json`; `scripts/load_odds.py`
ingests them into the existing `market_line` table as a proper time series —
an OPEN row and a CLOSE row per selection, with `is_closing` set at ingest.

`make odds` then grades the whole season at those **real** prices:

- **How the market priced them:** OKC closed as a favorite in 94% of games,
  averaging a −10.5 spread and a −852 moneyline (89% implied); BOS −4.8 and −303.
- **Records vs the closing line:** OKC 64-18 straight up but **48% ATS**; BOS
  56-26 SU, 60% ATS, and its games hit the **under** 63% of the time.
- **The $500 answer, priced for real:** betting both teams to win at their
  actual moneylines nets about **+$18 on $500** across the entire season — a
  rounding error, not a system. The gaudy 73% win rate is fully charged for by
  the price. Every other flat strategy lands within a few percent of break-even.
- **CLV:** betting the opening moneyline and grading against the close beat the
  closing number just 51% of the time (avg +0.9%) — statistically nothing.

The conclusion, now backed by real prices rather than an assumed −110: **with
public data there is no edge in betting good teams to win.** The market's
closing line already knows they are good. Any real edge lives in *price* —
catching a stale number before the market corrects it — which is what the
`bet` / `bet_grade` ledger and `fair_price` devig in `004` exist to measure, and
which needs many books, not one. More box-score, quarter, or odds *history* does
not manufacture that edge; it just lets you prove, honestly, when it is absent.

## Strategy lab (`make strategies`)

`scripts/strategies.py` tests a **menu of ~16 situational strategies** against
the real closing lines — angles the odds and game-date data newly make possible:
line-movement follow/fade (open→close steam), rest and back-to-backs, favorite
size, home/road, underdog value, and walk-forward ATS streaks. Each is graded at
the real price (ATS/totals at −110, moneyline at the actual number).

Several clear the −110 break-even in-sample (e.g. "cover as underdog" 62%,
"follow steam" 58%). That is exactly the trap, so two guards run afterward:

- **Guard 1 — coin-flip null.** Re-runs all strategies on random outcomes 3,000
  times and takes the best each time. The best *real* ATS/total ROI (+18.5%) is
  matched by pure noise about **24% of the time** — i.e. a season routinely
  hands you a "winner" that good when nothing is real.
- **Guard 2 — out-of-sample.** The best strategy on the first half of the season
  ("fade steam", +32% ROI) collapses to **−1.5%** on the second half.

Different strategies, same honest verdict as `research/backtest.py`: **no edge
you could have bet in advance.** The only durable signal remains CLV — beating
the closing price — which needs multiple books to exploit, not more strategies.

## Devig, fair price, and CLV (`make edges`)

A second, independent book is what you would devig and compare to hunt for a
mispriced number — but **no free historical, independent book proved reachable
for 2025-26**: ESPN backfills only ESPN BET, and The Odds API / SportsGameOdds /
odds-api.io all require a paid key. So `scripts/edges.py` builds the workflow a
second book plugs into, using the one book we have, and populates the market
half of the schema the earlier steps left empty:

- **Devig → `fair_price`.** Strips the vig from each closing moneyline
  (multiplicative method) into a vig-free fair probability. The book's average
  moneyline overround is **4.3%** — the house edge every bet starts behind.
- **Market internal consistency.** The closing *spread*-implied P(home win) and
  the closing *moneyline*-implied P(home win) agree to within a mean 0.5% (sd
  3.3%). Betting the >3% disagreements goes 50-27 (65%!) but **−14.5% ROI** —
  a perfect reminder that a high hit rate on favorites still loses money. No
  exploitable inconsistency.
- **CLV ledger → `bet` / `bet_grade`.** Bets each opening price and grades it
  against the devigged closing fair value. The open beats the fair close just
  28% of the time; average EV **−4.0%**, essentially the full vig. This
  reconciles with `make odds` (open beat close on raw *price* ~51% of the time,
  +0.9%): the line drifts your way a hair, but that drift is swamped by the 4.3%
  vig, so there is no positive EV inside one book.

The verdict, now with the machinery fully built: the blocker is **data access
(a keyed odds API), not the model**. `fair_price`, `bet`, and `bet_grade` are
populated and ready — feed them a sharp second price (e.g. Pinnacle) and the
pipeline flags every game where the two fair probabilities diverge, which is the
only edge this project has ever pointed to.

## Second-half player scoring (`make second-half`)

Player props — especially half-props — are the **softest, least efficient
market**, so "bet a key player's second-half points" is the most promising angle
in the project. `scripts/second_half.py` builds the scoring side of that bet from
the play-by-play: each key player's Q3+Q4 points per game (mean, std, floor,
ceiling) and the team's second-half total. On 2025-26, SGA is the steadiest —
15.9 ± 5.1 in the second half with a floor of 4 — while the team 2H totals are
tight (OKC 58 ± 8, BOS 55 ± 9).

The **data wall** is the price side: ESPN's free historical odds carry full-game
player point props, but **no second-half player props**, and their over/under
side is unlabeled and not bulk-queryable — so 2H prop *bets* can't be graded in
dollars here. The number to exploit isn't the average (the book sets the line
there) but the **dispersion and floor**: a low-variance star whose 2H points
rarely dip below a number is where a soft half-prop line leaks value. Capturing
it needs a props-capable odds feed (a keyed API), which is the same data-access
wall every step of this project has ended on — not a modelling limit.

## Fade-a-team test (`make fade TEAM=WSH`)

`scripts/fade_team.py` answers "bet team X to lose every game" at real closing
lines for any team (fetches its season + odds from ESPN, falling back across
books since ESPN backfills DraftKings for some games and ESPN BET for others).

On the 2025-26 **Wizards (17-64)**: they lost 79% of the time, but betting them
to lose means backing their opponents at an average −752 moneyline, so it
returns **−2%** — the price already knows they are bad, the exact mirror of
betting good teams to win. Fading them **ATS** went 48-33 (59%, +$66), which
looks alive but is z=1.7 / p=0.10 on 81 games — a likely fluke. Running the same
tool on **Utah (22-60)** confirms it: fading the Jazz ATS came in at exactly
41-41 (**50%**). One season on one team can't tell a real angle from a hot
streak, and the "fade the tank team" angle regresses to the coin flip the vig
turns into a loss.

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
