# ESPN basketball assistant

Run from the repository root with `python -m basketball`. Basketball has its own
configuration and data directory; the Yahoo and ESPN hockey workflows are independent.

The historical test found a retirement eligibility failure and worse fixed
starting-nine totals than the archived ESPN comparison. The picker is not ready
for unattended real drafting. Read [the results](BASKETBALL_BACKTEST_RESULTS.md)
and [the frozen evaluation protocol](BASKETBALL_BACKTEST_PROTOCOL.md).

The [enriched strategy experiment](BASKETBALL_STRATEGY_RESULTS.md) compares ten
common policies across four seasons, with independent ranks/projections and
2025-26 held out from strategy selection. Its [registered protocol](BASKETBALL_STRATEGY_PROTOCOL.md)
defines the data, fixed parameters, opponent models and limitations. These are
deterministic Python simulations with fixed seeds; the operator does not choose
historical picks manually. Historical rankings are a market proxy, not actual ADP.

```sh
python -m pip install pdfplumber
python -m basketball.strategy_lab prepare
python -m basketball.strategy_lab draft
python -m basketball.strategy_lab develop
python -m basketball.strategy_lab test
```

The phases separately collect pre-draft inputs, lock decisions, select using only
development seasons, and score the chronological test. Changed sources/inputs
invalidate the lock. The experiment saves captures, complete league rosters,
checksums and scored rows under ignored `basketball/data/strategy-lab/`. The
production picker is not changed or automatically replaced by an experiment winner.

The [rank-gap experiment](BASKETBALL_RANK_GAP_RESULTS.md) tests
`expert rank - ESPN rank` at every pick, including an unrestricted rule and a
one-round expert-rank window. It completed 720 deterministic drafts and records
8,640 target picks with their alternatives. Neither gap policy beat best expert
available on average in any of the five comparisons. In the dated 2024-25
published-board comparison, starter points changed by -5.45% and -1.73%,
respectively. Historical API ranks lack verified preseason timestamps; those
comparisons are explicitly retrospective diagnostics. Read the
[protocol](BASKETBALL_RANK_GAP_PROTOCOL.md) before interpreting the results.

```sh
python -m basketball.rank_gap prepare
python -m basketball.rank_gap draft
python -m basketball.rank_gap score
```

## Player and NBA team ban list

Ban a player by name or ESPN player ID, or ban an entire NBA team by name,
abbreviation or ESPN NBA team ID. Player bans survive trades because they use
player IDs. Team bans cover every player on that NBA team, including new arrivals
confirmed by the current public roster check. Fantasy team numbers are separate.

```sh
python -m basketball draft bans
python -m basketball draft ban player "Player Name"
python -m basketball draft ban player 3468
python -m basketball draft ban team LAL
python -m basketball draft unban player 3468
python -m basketball draft unban team LAL
```

These commands edit local preferences, without submitting ESPN draft commands.
Player names resolve against the saved snapshot; adding numeric player IDs,
listing bans and removing existing bans work offline. NBA team additions use the
public ESPN team catalog and reject ambiguous names. Use the listed name, ID or
abbreviation when removing a ban. Repeating an addition updates the same entry.

Bans persist in gitignored `basketball/data/draft-bans.json` (the configured data
directory) until explicitly removed, including across restarts and seasons. They
are applied to live draft recommendations, rankings, draft sheets, automatic
selection and explicit picks, queues and bids through both transports. The ban
list is reread before submission; changes take effect while the watcher runs.
No injury-risk acceptance overrides a ban. Malformed ban data stops drafting.
When every candidate is excluded, the assistant stops instead of relaxing bans.
No players or teams are banned by default.

The list controls this assistant's draft actions. It does not change ESPN's own
auto-pick preferences or remove players already queued on ESPN. If ESPN takes
over after a timeout/disconnection, its choices remain outside this control.
Existing rosters, season waiver/trade actions and historical backtests are not
changed by draft bans.

## Current availability before draft writes

Every API pick, queue addition and auction bid now requires fresh public ESPN
profile, current-team roster and injury-report evidence. The browser fallback
uses the same gate. The clock/turn are checked again after these reads and before
submission. Evidence is included with the API intent journal and receipt.

```sh
python -m basketball draft availability "Russell Westbrook" --refresh
python -m basketball draft availability 3468 --refresh
python -m basketball draft review-risk "Player Name" --reason "Accept the documented short injury at this price" --hours 2
```

Names resolve against the fantasy snapshot; numeric ESPN IDs support a standalone
public check without a private league read. Reports record sources, source times,
retrieval/expiry times and the reason for their decision. Public reads send no
ESPN account cookies. Ordinary checks cache source responses for at most 15
minutes; actual draft writes force new reads. Stale/wrong-season/missing sources,
ambiguous player identity or absent current roster membership never clear a player.

Inactive players and structured out-for-season injury designations are blocked.
Other injuries, suspensions and conflicting fantasy status require review and
are skipped by automatic drafting. A deliberate `review-risk` accepts only the
exact verified concern for up to 24 hours; a changed status, return date or report
invalidates it. Blocked/unknown players cannot be overridden through this command.
The automatic watcher checks candidates in order among its first 20 legal
recommendations, skips those without clearance, and stops if none is verified.

This checks current reported participation, not future injury proneness. A player
cleared here can still be injured later; data can be wrong even when fresh.
The public profile legitimately omits its optional injury field for healthy
players, so roster injury coverage and the separate injury feed are mandatory.
ESPN-controlled auto-picks after a disconnected/stopped client are outside this
gate. Expert ranks and projections are not modified or discounted again.

Live read-only validation on October 17, 2026: Russell Westbrook (3468) was
blocked as inactive, Henri Veesaar (5105571) was blocked with an OFS designation,
and Shai Gilgeous-Alexander (4278073) was clear on current sources. No live draft
write was submitted. Twelve focused availability tests and the existing 23 draft
protocol tests pass, including checks that failures send no command and clock
expiry during verification prevents a pick. Historical backtest source files are
unchanged; this current-data gate does not enter historical simulations.

## This league

Settings were read from the signed-in ESPN league settings page on **October 16,
2026**, rather than copied from the hockey league:

- League **2141453434**, team **18**, season **2027**; 16 teams; head-to-head points.
- Snake draft **October 18, 2026 at 11:00 a.m. EDT**; 60 seconds per selection.
  ESPN randomizes the order an hour beforehand. Set `draft.slot` after that, or
  use `settings --sync` / `draft watch` when ESPN exposes the order.
- Starters: PG, SG, SF, PF, C, G, F, UTIL, UTIL; 3 bench; 2 IR.
  Maximum 4 players with a primary center designation.
- Daily lineups lock individually at scheduled game time. No games-played cap.
- 4 acquisitions per matchup; no season acquisition limit; 1-day rolling waivers.
- Scoring: FGM 2, FGA -1, FTM 1, FTA -1, 3PM 1, REB 1, AST 2,
  STL 3, BLK 3, TO -2, PTS 1.
- 18 regular-season matchups; 8 playoff teams; playoff rounds last 1, 1 and 2 weeks.
  The trade deadline is February 26, 2027 at noon EST, with one-day trade review.

The checked-in authority is `basketball/league.json`. `settings --sync` imports
API scoring, slots, primary-position limits, lock type, acquisition/waiver rules,
draft settings and trade deadline while preserving local owner policy. Unknown
scoring/lock types stop the import. Games-cap formats vary across ESPN leagues:
configure those explicitly rather than assuming a numeric enum's meaning.

## Setup and data

```sh
python -m pip install -r requirements-basketball.txt
python -m playwright install chromium
python -m basketball login
python -m basketball fetch
python -m basketball settings
```

`login` opens a separate visible browser for interactive ESPN sign-in and saves
only ESPN's `espn_s2` and `SWID` cookies in `basketball/data/auth.json`. It never
asks for or stores a password. Alternatively set `ESPN_S2` and `ESPN_SWID` in the
environment. The Codex in-app browser's login is a separate session and is not
automatically shared with the command-line program. Windows needs `tzdata` for
the configured `America/New_York` timezone.

`fetch` reads all league rosters, the paginated full player pool, ESPN season
projections and historical/current NBA stats, ADP/auction values when available,
professional schedules, standings, matchups, draft results, pending activity,
and acquisition history for the current matchup's elapsed scoring periods.
Repeated pages or truncated acquisition history cause an error. Acquisition usage
comes from ESPN; an unknown count disables acquisitions instead of treating it as zero.

If direct cookie-based reads are unavailable, open a signed-in league page with
`leagueId` and `seasonId` in its URL. Run `scripts/basketball_read.js` in the browser
developer console. It performs reads only and downloads `basketball-export.json`:

```sh
python -m basketball import /path/to/basketball-export.json
```

No credentials are included in that export. It contains private league data, so
keep it local. The default data directory, export and generated task files are
gitignored. A custom configuration may use a different `data_dir`; keep that
directory outside version control too.

Every analysis command accepts global `--fetch` to refresh first, or
`--snapshot FILE` to analyze a normalized offline snapshot. Global options go
**before** the command:

```sh
python -m basketball --fetch report
python -m basketball --config basketball/league.json --snapshot /path/to/snapshot.json report
```

## Projections and rankings

ESPN's current-season projection is the prior when available. Otherwise the model
blends the previous two NBA seasons with 65/35 recency weights. Actual production
updates the prior with a configurable 20-game prior weight. Projections use NBA
schedule dates and projected availability rather than hockey dates or a simple
elapsed-calendar fraction. An unprojected player remains unranked and is never auto-added.

The same player values feed draft rankings, lineups, acquisitions and trade math.
Draft VOR uses season value and estimates replacement depth by distributing
league-wide primary, shared and bench slots across primary positions. This is a
scarcity approximation, not a full league-wide roster simulation.

```sh
python -m basketball rankings --limit 200 --csv basketball/data/rankings.csv
python -m basketball cheatsheet --out BASKETBALL_DRAFT_SHEET.md
python -m basketball roster
```

Manual research overrides are keyed by **ESPN player ID** in `adjustments`:

```json
{"adjustments": {"12345": {"games": 65, "multiplier": 1.05, "per_game": {"AST": 6.2}}}}
```

For another league, copy the configuration and pass `--config`. Supported formats
are `points`, `categories`, and `roto`. Category values use population-standardized
counting stats, attempt-weighted FG/FT percentage impact, explicit category direction,
and optional `punts`. Team percentages always aggregate makes and attempts. Roto
standings require actual season totals for every team; missing totals are reported.

## Drafting

```sh
python -m basketball draft reset
python -m basketball --fetch draft sync
python -m basketball draft best --slot 3 --pick 30 --limit 20
python -m basketball draft taken "Nikola Jokic" --team 1
python -m basketball draft mine "Shai Gilgeous-Alexander"
python -m basketball draft undo "Nikola Jokic"
python -m basketball draft paste "pasted draft results here"
python -m basketball draft watch --slot 3
```

`paste` marks known names taken; record your players with `mine`. Players are keyed
by ESPN ID, with unique name/substring matching as a convenience. `sync` imports
ESPN picks idempotently. Manual records remain available when REST draft results
lag the room. A drafted ID missing from the player pool stops recommendations
until the full pool is refreshed.

Recommendations enforce roster/position limits and leave enough selections to
complete the starting slots. They include ADP and a **conditional ADP heuristic**
for survival until your next snake pick. This is not a calibrated probability or
a prediction of individual opponents' behavior. Missing ADP stays unknown.

Auctions use recorded spending, remaining cash, minimum-bid reserves and available
VOR to estimate inflation-adjusted fair value and maximum bids:

```sh
python -m basketball draft mine "Player Name" --cost 35
python -m basketball draft taken "Other Player" --team 2 --cost 28
python -m basketball draft auction "Target Player" --current-bid 20
```

Record all auction spending and team IDs for meaningful league-inflation estimates.
This league uses a snake draft; auction tools are available for configurations
with `draft.type` set to `auction`.

### API picks, queue and bids

```sh
python -m basketball draft pick "Player Name"
python -m basketball draft queue "Player Name"
python -m basketball draft bid "Player Name" --amount 20
python -m basketball draft status
python -m basketball draft pick "Player Name" --execute
python -m basketball draft queue "Player Name" --execute
python -m basketball draft watch --execute
```

Pick, queue and bid commands preview by default. With `--execute`, they use
ESPN's live **WebSocket draft API**. No browser controls are needed for execution.
`draft watch --execute` maintains a connection, updates the model from server
events, and selects the best legal player on your snake turns. It reads current
rules and projections from `draftInit`; it does not require a prior snapshot.
Live turn ownership comes from the server, including traded picks, rather than
assuming a slot number. `--slot` only influences ADP timing recommendations.

The client obtains an account/team-specific `draftSecurity` token using the
saved ESPN login, connects to `wss://fantasydraft.espn.com/game-3/league-ID/JOIN`,
and decodes the versioned binary INIT payload. Snake picks use `SELECT playerID`,
queues preserve existing order with `DRAFT_LIST`, and explicit auction bids use
`BID playerID amount`. Authentication tokens stay in memory and are omitted from
logs and error messages. Opening a second connection for the same ESPN account
may disconnect its existing browser draft room.

Before a pick/bid, the server must confirm a live draft, the correct turn/player,
a legal remaining roster and at least 25 seconds on the clock. A ping response
barrier drains older events before validation. Auction bids additionally enforce
the live price, model maximum, and roster-completion cash reserves. API queue
execution and automatic watch currently support snake drafts; auction bidding
is explicit. Auction nomination and queue editing are not implemented.

Commands are journaled in `draft-write.json` before sending and sent **once**.
Success requires the matching `SELECTED`, `DRAFT_LIST` or `BID` server event;
winning an auction can also confirm the matching bid. A failed connection or
missing receipt leaves a pending intent that blocks further writes:

```sh
python -m basketball draft reconcile
# Only after personally checking ESPN and confirming it did not execute:
python -m basketball draft resolve --not-executed
```

Reconciliation can recover a pick from a new INIT even when its original receipt
was lost. Bid confirmations show that ESPN accepted a bid; another owner can
outbid it immediately. Pending bids that were subsequently outbid may need owner
resolution. Verified actions and explicit resolutions are retained in
`draft-receipts.json`. Protocol changes, draft undo/reset and unknown schemas
stop execution and require reconnecting. There is no automatic browser fallback.
On completion, `draft watch` saves `draft-result.json` with the final server
state and your roster's names/projections; custom mock leagues may disappear
immediately afterward.

For practice, use a separate configuration with the practice league ID and a
separate `data_dir`. Never reuse the real league's draft journal for a mock.
Sign in with that configuration, then run `draft status` before any write.

The transport follows ESPN's own
[basketball draft client (build 449ae61ae2f5-1.520)](https://cdn1.espn.net/kona/449ae61ae2f5-1.520/_next/f8bbd749-dc6b-4853-92a4-4ed40e7db182/page/basketball/draft.js),
inspected October 16, 2026. This is an unofficial protocol that ESPN may change.

### Optional browser fallback

Pass `--transport browser` to `draft pick`, `queue`, `bid` or `watch` to explicitly
use the earlier Playwright implementation. It still needs configuration below.

**Rehearse and configure the actual draft-room controls first.** ESPN's room is
not a stable public automation API. The implementation requires a unique exact
player row and verified ESPN player ID, enabled action button, visible turn marker,
and at least 25 seconds on the clock. Unknown controls stop execution.

`draft_ui` supports `row_selector` (default `tr`), `player_id_attribute` (default
`data-playerid`, with player headshot ID as a fallback), `clock_selector`,
`turn_selector`, `turn_pattern`, `pick_button`, `queue_button`, `bid_button`,
`bid_input_selector`, `queue_selector`, and `bid_status_selector`. Supply selectors
from the observed room. No guessed clock selector is supplied. Picks are verified
against ESPN results; queues and bids require visible confirmation. If verification
fails, inspect the room before retrying. Automatic auction bidding is not a watch
mode; each bid is an explicit command checked against the model's maximum.

## Managing the season

```sh
python -m basketball --fetch report
python -m basketball lineup --days 7
python -m basketball stream --days 7
python -m basketball stream --days 7 --target-opponent
python -m basketball matchup
python -m basketball standings
python -m basketball playoffs
python -m basketball playoffs --weeks 2027-03-01 2027-03-08
```

Daily lineup selection uses exact maximum-value position matching and preserves
players whose games have started, including locked bench players. It fills unused
active slots legally instead of overflowing the bench with players who have no
game. Weekly configurations keep one lineup throughout the modeled matchup.
IR moves require both an eligible status and ESPN IR slot eligibility. Healthy IR
players are activated only when a non-IR roster spot is available.

Streaming evaluates the **actual improvement to the scheduled starting lineup**,
including congestion and conservative waiver-clearance delays. Recommendations are
single-move alternatives; recompute after each acquisition. Pending claims, protected
players, ESPN undroppables, acquisition limits, center limits and starting-position
coverage constrain executable moves. Injured players are assumed unavailable until
a later read changes their status. Future rest/load management is not predicted.

Matchup reports combine available cumulative stats with remaining-game forecasts.
Category targeting emphasizes close categories with a documented heuristic. Games
already started are not counted again in remaining forecasts. Future opponent
lineups are modeled, not known. Playoff dates come from ESPN's scoring-period map
or explicit week-start dates; no playoff calendar is invented.

For a capped league, configure `games_caps`, such as `{"ALL": 820}` or per-slot
limits, and supply authoritative `games_used` in the snapshot. Missing usage stops
cap-dependent planning. These are hard forecasting caps; ESPN remains authoritative
for its own scoring rules and any end-of-day cap overshoot behavior.

### Acquisitions and owner commands

```sh
python -m basketball swap "Add Player" "Drop Player"
python -m basketball swap "Add Player"
python -m basketball swap "Waiver Player" "Drop Player" --bid 5
python -m basketball command "add Add Player drop Drop Player"
python -m basketball command "drop Drop Player, add best PG if better"
python -m basketball command "yes B1234abcd"
python -m basketball apply
```

All preview by default. `swap` without a drop fills an open spot. FAAB bids are
accepted only for FAAB waiver claims and must fit the remaining budget and minimum.
The deterministic owner-command parser recognizes roster/report queries, named
add/drops, best-position replacements and stable proposal IDs from a fresh report.
It cannot change league settings or send arbitrary messages.

`apply --execute` refreshes ESPN under a process lock, applies/validates lineup
changes, then recomputes before making **at most one** automatic acquisition.
The default policy permits two auto adds per matchup, requires +100 modeled ROS
points, and respects protected/undroppable players and the league's four-add limit.
Edit those policy values for category leagues. Trades are never automatic.
Management runs issue no actions before the draft is complete or while the roster
is empty. The commands do not inherit the hockey league's Monday-only restriction.

### Trades

```sh
python -m basketball trade --team 2 --give "Our Player" --get "Their Player"
python -m basketball trade-ideas
python -m basketball trade --team 2 --give "Our Player" --get "Their Player" --propose
python -m basketball trade-response OFFER_ID --accept
python -m basketball trade-response OFFER_ID --decline
```

Trade evaluation supports multiple players per side, compares both teams' best
lineup values, and credits replacement-level available players instead of valuing
empty slots at zero. Trade ideas are one-for-one proposals that improve both sides.
Uneven trades that exceed roster limits require resolving the roster opening first.
Evaluation is advisory: it does not model every future bench rotation or trade-review delay.

`--propose --execute` sends an explicitly requested offer. A trade response needs
`--execute` too, and must reference an incoming ESPN offer involving this team.
Acceptance checks current ownership, deadline and roster limits. Offers/acceptances
are not reported as completed player transfers until fresh ESPN state confirms them.

## Automation, audit and recovery

```sh
python -m basketball --fetch run
python -m basketball run --execute
python -m basketball run --watch 900 --execute
python -m basketball schedule --time 10:30
python -m basketball schedule --time 10:30 --execute
```

`run` emits a structured report and stores executed-run summaries locally.
`--watch` is a portable foreground loop. `schedule` generates Windows Task Scheduler
XML or a Unix cron entry with absolute paths and prints installation instructions;
it does **not** install a task. The host scheduler's timezone must match the league
timezone. Keep the checkout containing the scheduled command available; after merge,
regenerate scheduler files from your permanent checkout before removing the worktree.
No iMessage or macOS paths are required. Existing hockey iMessage handling remains
separate; a notification integration can consume the basketball command's JSON output.

Writes require authenticated cookies, are journaled before submission, and are
reread afterward. Credentials/member IDs are omitted from transaction logs.
A timeout or interrupted submission has an unknown outcome and **blocks further
writes** rather than being retried automatically:

```sh
python -m basketball --fetch reconcile
```

If ESPN shows that a request was refused/cancelled and is not pending, inspect the
one-based entry in `basketball/data/transactions.json`, then explicitly attest:

```sh
python -m basketball --fetch resolve-write 1 --not-executed
```

This refuses an entry confirmed by current ownership or still listed as pending.
Do not use it simply because a waiver has not cleared yet. Lock directories are
removed on normal exit; inspect a stale `basketball/data/.lock` after a hard process
termination before removing that empty directory.

## Verification limits and tests

League settings and projection columns were verified in the signed-in ESPN
website. The direct draft API completed a 16-team practice draft: 11 picks were
confirmed through the API and one was auto-picked by ESPN after a clock guard
stopped a 30-second turn. The remaining rehearsal used the real league's 60-second
timer. See [the rehearsal record](BASKETBALL_API_REHEARSAL.md) for the roster and
exact scope. No real-league picks, roster transactions, bids or trade offers were
submitted. Auction bids, season writes and browser controls have local coverage
but remain unverified live on this account. ESPN's unofficial contracts can change.

ESPN mappings/reference implementations:
[espn-api basketball](https://github.com/cwendt94/espn-api/tree/master/espn_api/basketball),
[settings field reference](https://github.com/pseudo-r/Public-ESPN-Fantasy-API/blob/main/docs/settings.md),
[transaction envelope notes](https://github.com/DanielTomaro13/sportsdata-mcp/blob/main/documentation/ESPNFantasy.md).

```sh
python -m unittest discover -s tests -p test_basketball.py -v
python -m unittest discover -s tests -p test_basketball_draft_api.py -v
```

Tests are limited to the basketball backend and do not contact ESPN. They cover
exact matching against an exhaustive oracle, lock handling, scoring/projection
updates, category percentages/punts, caps, IR, acquisition constraints, draft/auction
state, command previews, trade checks, and uncertain-write recovery. Draft API
tests cover INIT decoding, authentication, command acknowledgements, turn/clock
guards, queue preservation, immediate auction outbids and disconnect recovery.
