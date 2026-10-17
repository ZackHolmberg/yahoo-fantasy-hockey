# Ranking-source backtest protocol

Registered after collecting the source inventory, before drafting or grading these comparisons. This is retrospective evaluation: outcomes for these years have been used in earlier work or as prior-season inputs. No new blind holdout or optimized winning strategy is claimed.

## Fixed inputs

Use the six frozen ranking-library packs for seasons ending 2018, 2019, 2023, 2024, 2025 and 2026, checked against the committed data inventory. Keep their shared player universes, published/prior positions, unresolved-ID exclusions and original ranks. No 2026–27 current boards, current bans, current availability, category boards, revised historical API ranks or target-season statistics enter draft decisions.

Use the configured 16-team snake league, 12 roster spots, nine starters, four-primary-center cap and exact points scoring. The common per-season candidate pool includes players who appeared in the immediately prior NBA season or appear on any accepted preseason board. All policies and opponents share that pool and enforce roster legality and ability to fill starters.

## Policies and missing coverage

* `espn`: best legal published ESPN rank, followed by prior-season total points for unranked players.
* `prior_total`: best legal prior-season total fantasy points on the same common pool.
* One `source:<id>` policy for each independent historical board, including RotoWire's early snapshot, total-points and per-game variants. Take that board's best legal published rank first. Players absent from the recovered board follow the completed ESPN order. Never relabel this tail as a published rank or custom-scoring projection.
* `publisher_consensus`, only in the three seasons with multiple publisher families: average completed preference positions with equal weight per publisher. Use one board per family. Within a family prefer a non-per-game board, then the most recently published dated snapshot, with source ID as the deterministic final tie-breaker. This picks the September total-points RotoWire list rather than its July snapshot or per-game variant in 2025–26. ESPN, RotoWire and Rotoworld each receive one vote where available. No outcome-fitted weights.

All preference ties resolve by ESPN completed position, then player ID. Ranking lists retain their different native scoring assumptions; incomplete numerical forecasts are not rescored with invented shooting inputs. Partial top-50/top-100 policies test the recovered prefix plus the declared ESPN tail, not a hypothetical full paid board. Report the fraction of picks covered by each source.

## Opponents, sample and locks

Each season uses an ESPN opponent field. Seasons with a distinct publisher consensus also use a consensus opponent field. Each field has exact ordering (seed -1) and two deterministic Gaussian perturbations with standard deviation 12 preference positions (seeds 0, 1). Test all 16 target draft slots. Opponent preferences are identical across paired policy arms. Consensus opponents use the same latest-board rule as the consensus policy, without knowledge of outcomes.

This yields 1,728 complete leagues: 96 each in 2017–18, 2018–19 and 2023–24; 384 in 2022–23; 480 in 2024–25; and 576 in 2025–26. Retain all team rosters and target-pick traces. Hash inputs, configuration, source code and draft decisions before reading outcomes in the grading phase; commit the decision lock before scoring.

## Grading and interpretation

Score actual season points for all 12 players and for the hindsight best legal fixed nine starters, plus zero-game picks, fewer-than-25-game picks and source-covered pick share. Pair each case with ESPN for the same season, opponent field, seed and slot. Publish mean percentage differences, strict paired starter wins and 10th/90th percentile starter differences. A paired win is not an H2H league championship.

Publish each season/field/source separately. Aggregate only comparable policies using equal weight per season after averaging that season's fields/slots/seeds. Do not compare a publisher's single available season with a different publisher's six-season average as if they were the same test. Seeds and slots are correlated; these are not 1,728 independent historical seasons. Do not tune on the results, substitute hindsight injury exclusions, or deploy a best retrospective performer automatically.

Also report the primary RotoWire board's equal-season average across its three available seasons, using the same non-per-game/latest-publication rule registered for consensus membership. Its baseline comparisons use ESPN on those same seasons. Older snapshots and per-game variants remain separate diagnostics, not additional independent votes.

Independently verify raw outcome totals and the fixed-nine calculation with a separate slot-bitmask optimizer; validate full-league identity uniqueness, roster size, center caps, starter coverage, pick traces and a repeated real-input draft. Preserve all earlier experiment source files/locks. No daily congestion, weekly matchups, waivers, trades or playoff progression are simulated.
