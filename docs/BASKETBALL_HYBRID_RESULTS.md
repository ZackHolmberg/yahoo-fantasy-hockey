# Expert rankings with market timing

Implemented an opt-in, read-only advisor that keeps expert quality primary and
compares taking a favorite now with taking another strong player and seeking the
favorite next turn. It improved the retrospective averages modestly. Most of the
benefit still comes from the expert boards, rather than the timing adjustment.

## Paired results

576 new deterministic full 16-team drafts, paired with 864 existing baseline
drafts: **1,440 cases** across 2022–23, 2024–25 and 2025–26, all 16 snake slots,
ESPN-following and consensus-following opponents, and exact plus two seeded
opponent-order variations. Gains average seasons equally. Starter points mean
the hindsight best legal fixed nine for the entire season, not weekly lineup
results or championships.

| Quality source | Expert-first vs ESPN | Hybrid vs ESPN | Hybrid vs same expert-first | Full-roster timing gain |
|---|---:|---:|---:|---:|
| RotoWire | +3.20% | +3.46% | +0.27% | +0.18% |
| Publisher consensus | +2.71% | +3.19% | +0.47% | +0.54% |

The paired timing gain uses each expert-first roster as its denominator, so it
does not equal simple subtraction of the two ESPN-relative averages.

| Season | RotoWire hybrid vs ESPN | Timing vs RotoWire | Consensus hybrid vs ESPN | Timing vs consensus |
|---|---:|---:|---:|---:|
| 2022–23 | +2.11% | +0.17% | +1.26% | -0.18% |
| 2024–25 | -2.78% | +0.04% | +0.79% | -0.11% |
| 2025–26 | +11.06% | +0.60% | +7.50% | +1.70% |

Against the same greedy expert policy, RotoWire timing improved 64 drafts,
worsened 39 and tied 185 of 288; consensus timing improved 51, worsened 39 and
tied 198. The hybrid deferred its best legal expert in 4.05% of RotoWire picks
and 3.82% of consensus picks. Zero-game selections slightly increased: RotoWire
0.076 to 0.087 per roster; consensus 0.080 to 0.087. Timing does not replace the
current availability check.

## Opponent sensitivity

Each cell is hybrid starter gain over its matching expert-first policy, averaged
over all 16 slots and three opponent-order variants.

| Season | RotoWire: ESPN field | RotoWire: consensus field | Consensus: ESPN field | Consensus: consensus field |
|---|---:|---:|---:|---:|
| 2022–23 | -0.06% | +0.40% | -0.05% | -0.31% |
| 2024–25 | +0.20% | -0.11% | -0.05% | -0.18% |
| 2025–26 | +0.54% | +0.66% | +2.92% | +0.48% |

The average gain is small and concentrated in the most recent season. Consensus
timing lost its first two annual comparisons. This is not evidence of a reliable
universal improvement or an optimal strategy; keeping expert-first as a fallback
is sensible. The default automatic drafting policy was not changed.

## How it avoids reaching

Only consider players within seven completed expert-order places of the best
legal player. Compare the current and next selection across six public demand
scenarios, including opponents who follow experts rather than ESPN. Choose the
pair with the best mean rank utility. Ties, final picks and consecutive picks
favor the best expert immediately. Opponent demand is an approximation, while
our roster constraints apply to both selections. It does not simply choose the
largest expert-minus-ESPN rank gap or impose an arbitrary ADP cutoff.

For example, in a 2025–26 RotoWire simulation at pick 65 with the next turn at 96,
the best legal expert was Immanuel Quickley (quality order 45; ESPN 100). The
hybrid selected Alex Sarr (quality order 48; ESPN 75), preserving a chance at
Quickley next turn. Quickley survived in three of the six forecasts. That count
describes sensitivity to assumed demand, not a 50% calibrated probability or a
guarantee. The rule can take the favorite immediately when the tradeoff is worse.

## Current-season advisor

```sh
# At our turn; refresh league data and verify current NBA availability.
python -m basketball --fetch draft hybrid --source rotowire --verify
python -m basketball --fetch draft hybrid --source consensus --verify

# Supply a known slot when ESPN does not expose its pick order.
python -m basketball draft hybrid --source rotowire --slot 15 --verify
```

The advisor syncs completed snapshot picks into local tracking, reads ESPN's
STANDARD draft order and the checksummed current source library, and shows its
recommendation, expert favorite, published source ranks, candidate comparisons,
next pick and scenario forecasts. It requires our current snake turn and
consistent history. `--fetch` refreshes the league snapshot; it does not refresh
the separately collected expert articles. `--verify` checks the selected player's
current availability and retries alternatives that fail. Without it, the output
explicitly marks availability unchecked. Every existing executed pick/queue/bid
still independently enforces current availability and bans.

RotoWire, Rotoworld, FantraxHQ and publisher consensus are selectable. Current
consensus gives one vote each to ESPN and those three publishers. The historical
consensus includes only publishers recovered for each year, and Fantrax has no
accepted historical comparison in this dataset. Untested individual sources are
not implied to have the same results as RotoWire or the tested consensus.

A fresh authenticated read returned 1,096 players and 410 valid STANDARD ranks.
An isolated hypothetical opening-turn preview using the earlier cached practice
pool matched 148/150 RotoWire, 192/200 Rotoworld and 198/200 Fantrax rows and chose
Nikola Jokic. Missing/ambiguous names or absent ESPN ranks are listed explicitly;
no fuzzy identity matches or ranks are invented. Unpublished expert tails follow
ESPN. The current-season advisor uses the same chooser, but current source
coverage and live market data differ from historical input packs.

This command submits no picks and has no `--execute` option. Automatic watch
continues to use its existing policy. No league mutations were made for this
work. Current source files must already be collected using the ranking-library
workflow described in [the data inventory](BASKETBALL_DATA_SOURCES.md).

## Reproducibility and limits

The [protocol](BASKETBALL_HYBRID_PROTOCOL.md) and chooser were committed at
`c62b325` before generating drafts. The [decision lock](basketball_hybrid_lock.json)
was committed at `1d1f9f9` before grading. Decision SHA256:
`5b4cd53c4514010bd4fd8765177edc3e13a2195f2050f743b1d92a4f46909e84`.
No timing parameters were swept or adjusted after scoring. Earlier results were
already known, so this is a fixed retrospective extension, not a fresh blind test.

Independent raw-stat arithmetic and a separate slot-bitmask optimizer verified
all 1,440 scored targets (1,039 unique rosters). Full-league uniqueness, roster
size, caps and independent starter matching checked all 23,040 team-roster
records (8,562 unique rosters). Candidate windows, defer counts, pick traces and
paired gains were also checked independently. The earlier experiment locks still
validate. Twenty new targeted tests cover the chooser, current advisor and
experiment; the six existing source-backtest and 23 draft-API tests pass.

Historical RotoWire prefixes contain only 50 players in 2022–23 and 2024–25 and
100 in 2025–26. Missing expert ranks use ESPN completion. Source scoring is not
identical to this custom league; positional metadata and full-season outcome
limitations from the source study remain. Scenario forecasts do not know actual
opponent preferences or simulate opponent positional constraints. Rank utility
is not projected fantasy points. Seasonal outcome evaluation excludes waivers,
weekly scheduling and subsequent roster management.

Machine-readable aggregates and field comparisons:
[basketball_hybrid_summary.json](basketball_hybrid_summary.json).
Ignored runtime decisions, per-pick forecasts, outcome rows and independent
verification are in `basketball/data/hybrid-backtest/`.
