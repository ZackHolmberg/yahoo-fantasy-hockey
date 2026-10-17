# Six-season ranking-source backtest

Completed **1,728 deterministic 16-team drafts** across the six prepared seasons, every target draft slot, exact opponent preferences and two seeded variations per field. All choices were frozen and their hash committed before scoring this experiment. Outcomes for these seasons were already available in earlier work or as prior-year inputs, so this is retrospective evaluation rather than a fresh blind holdout.

The new sources improve the average comparison: primary RotoWire +3.20% starter points and publisher consensus +2.71% over ESPN on their three common seasons. Consensus has positive season averages in all three (+1.46%, +0.90%, +5.76%). RotoWire has the higher mean, but loses 2024–25 (-2.75%) and gains heavily in 2025–26 (+10.42%). These are promising retrospective candidates rather than proof of an optimal live strategy.

The sharpest total-versus-per-game comparison is 2025–26: RotoWire total points +10.42%, its per-game list -7.16%. The July snapshot also loses (-1.16%). This supports testing recent season-total boards and publisher consensus further. Opponent behavior matters: the 2024–25 consensus gains +6.01% against ESPN-following opponents but loses -4.20% against consensus-following opponents. Prior-season points win three of the older season averages, but their six-season mean is -4.98%, driven by a -41.91% 2025–26 failure. No parameters or publisher choices were retuned after seeing these results.

## Equal-season aggregates

Changes are paired against ESPN for the same season, opponent field, seed and slot. Each season receives equal weight after averaging its cases. Starter points mean the hindsight best legal fixed nine for the whole season; roster points include all 12 players. A paired win means higher starter points, not an H2H league championship.

| Policy | Seasons ending | Drafts | Starter change | Roster change | Paired wins | Zero-game picks / roster |
|---|---|---:|---:|---:|---:|---:|
| Prior-season points | 2018, 2019, 2023, 2024, 2025, 2026 | 432 | -4.98% | -5.95% | 47.7% | 1.06 |
| Publisher consensus | 2023, 2025, 2026 | 288 | +2.71% | +2.91% | 62.2% | 0.08 |
| Primary RotoWire board | 2023, 2025, 2026 | 288 | +3.20% | +2.37% | 62.5% | 0.08 |

The primary RotoWire aggregate uses its public top 50 in 2022–23 and 2024–25 and September total-points top 100 in 2025–26. The consensus is tested only where multiple publishers exist. All aggregate gains are against ESPN on the listed same seasons; a three-season comparison should not be read as six-season evidence.

## Every comparison

Each row averages all fields for that season (48 drafts per field/policy). Field columns expose whether the advantage changes when opponents use the consensus. “Covered picks” is the share on the source’s recovered published prefix; for consensus it requires a rank from every selected publisher. The rest use the declared ESPN tail. Prior-season points have no expert-board coverage.

| Season | Policy | Drafts | Starter change | Roster change | ESPN field | Consensus field | Paired wins | Covered picks |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 2017–18 | Prior-season points | 48 | +0.40% | +8.36% | +0.40% | — | 56.2% | 0.0% |
| 2018–19 | Prior-season points | 48 | +13.39% | +16.38% | +13.39% | — | 97.9% | 0.0% |
| 2022–23 | Prior-season points | 96 | +4.26% | +0.81% | +1.57% | +6.96% | 70.8% | 0.0% |
| 2022–23 | Publisher consensus | 96 | +1.46% | +1.97% | +0.21% | +2.71% | 59.4% | 38.6% |
| 2022–23 | RotoWire published expert order | 96 | +1.94% | +2.10% | -0.88% | +4.76% | 61.5% | 44.7% |
| 2023–24 | Prior-season points | 48 | -3.59% | -11.37% | -3.59% | — | 27.1% | 0.0% |
| 2024–25 | Prior-season points | 96 | -2.44% | -2.07% | -4.57% | -0.31% | 34.4% | 0.0% |
| 2024–25 | Publisher consensus | 96 | +0.90% | +1.56% | +6.01% | -4.20% | 57.3% | 36.5% |
| 2024–25 | RotoWire published expert order | 96 | -2.75% | -2.69% | -0.78% | -4.72% | 39.6% | 40.3% |
| 2024–25 | Rotoworld published expert order | 96 | -4.87% | -5.59% | +0.54% | -10.29% | 32.3% | 100.0% |
| 2025–26 | Prior-season points | 96 | -41.91% | -47.81% | -44.35% | -39.48% | 0.0% | 0.0% |
| 2025–26 | Publisher consensus | 96 | +5.76% | +5.19% | +9.39% | +2.13% | 69.8% | 59.7% |
| 2025–26 | RotoWire July snapshot | 96 | -1.16% | -4.25% | -0.47% | -1.86% | 43.8% | 82.6% |
| 2025–26 | RotoWire projected total points | 96 | +10.42% | +7.70% | +15.66% | +5.19% | 86.5% | 81.1% |
| 2025–26 | RotoWire projected points per game | 96 | -7.16% | -10.96% | -1.96% | -12.36% | 32.3% | 86.2% |

## Frozen decision rules

* ESPN takes its best legal published rank, then prior-season total points for unranked players.
* Each independent source takes its best legal published rank, then the completed ESPN order for players missing from its recovered board. This tests a top-50/top-100 prefix plus a stated fallback, not a hypothetical full paid ranking.
* Consensus averages completed preference positions with one equal vote per publisher. A family’s primary board is chosen before scoring: non-per-game first, then latest publication. In 2025–26 this uses September RotoWire total points, not its July snapshot or per-game list. ESPN and Rotoworld each also get one vote when present.
* Every policy and opponent shares the same season pool: prior-year NBA participants or players on any accepted preseason board. All draft choices preserve roster legality and the ability to fill the nine starters, including the four-primary-center cap.
* Current bans and current availability are excluded from past simulations. The new 2026–27 sources, category boards, post-opening-night revisions and historical API ranks without preseason timing are excluded. Numeric forecasts with missing shooting fields are not passed off as custom-league point projections.

Opponents use the ESPN order and, where different, the registered publisher consensus. Each field has an exact ordering and two fixed Gaussian perturbations (standard deviation 12 completed preference positions). Opponent preferences are identical across paired policies. Seeds and slots are correlated and are not independent historical seasons.

## Validation and reproducibility

Independent raw-total arithmetic and a separate slot-bitmask lineup optimizer verified all **1,728 target records** (1,581 unique scored rosters). An independent augmenting-path matcher checked starting-slot coverage for every team in all **1,728 complete leagues** (27,648 team-roster records). Full-league uniqueness, roster sizes, center caps, source-rank traces, source coverage and paired gain arithmetic also passed. Repeated real-input drafts match the frozen run. Six targeted backend tests cover source tails, publisher weighting, candidate-pool parity, legality, determinism, future-input rejection and tampering before outcome access.

Decision SHA-256: `95f54d018cb71917c1675fb0dcfbedaf265959bd279affabe1baa0301a8ef5fe`. See [the committed decision lock](basketball_source_test_lock.json), [registered protocol](BASKETBALL_SOURCE_TEST_PROTOCOL.md), [source inventory](BASKETBALL_DATA_SOURCES.md) and [machine-readable results](basketball_source_test_summary.json). Full inputs, all-team draft decisions, target-pick traces and scored cases are preserved under ignored `basketball/data/source-backtest/`.

```sh
python -m basketball.source_backtest prepare
python -m basketball.source_backtest draft
python -m basketball.source_backtest score
python -m unittest discover -s tests -p test_basketball_source_backtest.py -v
```

The older source packs have 582/632 players for seasons ending 2018/2019. The newer packs have 677/667/625/654 players. Published coverage differs, source scoring assumptions differ, prior/published positional fallbacks are documented, and Egor Demin’s ambiguous historical ID remains excluded from the new 2025–26 pack. Historical publisher/PDF dates are not independently authenticated original archive timestamps.

This fixed-nine hindsight proxy omits daily scheduling congestion, weekly matchups, waivers, playoff progression and trading. There is no new blind holdout, outcome-based tuning, or automatic deployment of the retrospective best performer. The production ranking strategy, ban list and current-availability guard are unchanged. No live league write was sent.
