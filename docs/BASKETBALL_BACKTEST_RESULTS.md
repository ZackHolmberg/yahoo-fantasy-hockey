# Historical draft test results

The current history fallback fails basic player eligibility. It drafted Carmelo
Anthony in **all 96 simulations for 2023-24**, scoring zero points from him.
He had [announced his retirement before that season](https://www.nba.com/news/carmelo-anthony-announces-retirement).
The model also produced worse starting-nine totals than the archived ESPN
comparison in both seasons for which that comparison was available.

This does **not** establish readiness for unattended drafting.

## What was held out

The [protocol](BASKETBALL_BACKTEST_PROTOCOL.md) was committed before the runs.
The model's strategy was not tuned after seeing the results. Draft selection
received only the previous two completed seasons' totals and prior-season fantasy
positions. Target-season results were supplied only to the scoring function.
Decisions, inputs and source files were hashed before scoring.

Reliable timestamped numeric preseason projections were not recovered. Therefore
this is a **history-fallback chronological holdout**, not a complete historical
test of the current ESPN projection-assisted strategy. It preserves the stale-
player failure rather than removing retirees using hindsight.

The experiment used this league's exact points weights, 16 teams, 12 roster
spots, nine starting slots and four-primary-center cap. Each season was tested
at every draft position against an ordered prior-points opponent board and five
seeded noisy versions. Both arms of a comparison received identical opponent
preferences. These are correlated simulations, not independent real leagues.

There were **384 model drafts and 576 baseline drafts**, producing **576 paired
comparisons**. Some comparisons share the same model draft. No live ESPN draft
or roster writes were used.

## Archived ESPN comparison

Both policies use the same veteran player universe. Archived ESPN points ranks
order the available listed players; unlisted players follow in prior-season
points order. Rookies without prior NBA games are absent. The 2022-23 sheet
contains 200 ranks; the 2024-25 sheet contains 150. This is an **archive-based
hybrid**, not an exact replay of ESPN drafts or ADP.

| Season | Comparisons | Mean paired gain: all 12 players | Mean paired gain: best fixed starting nine | Starting-nine wins |
|---|---:|---:|---:|---:|
| 2022-23 | 96 | +3.09% | **-2.23%** | 30/96 |
| 2024-25 | 96 | -1.07% | **-4.01%** | 40/96 |

The starting-nine metric uses the best legal fixed lineup in hindsight. It is a
season-total proxy, not daily lineup scoring or a head-to-head win probability.
Even under that optimistic measure, the model loses to this comparison on average.

## Simpler previous-season-points baseline

| Season | Comparisons | Model mean roster points | Baseline mean roster points | Mean paired gain | Pairs with higher model roster points |
|---|---:|---:|---:|---:|---:|
| 2019-20 stress case | 96 | 19,370.3 | 17,723.3 | +10.76% | 78.1% |
| 2022-23 | 96 | 25,826.3 | 21,858.3 | +19.26% | 95.8% |
| 2023-24 | 96 | 23,297.2 | 23,600.2 | **-0.55%** | 41.7% |
| 2024-25 | 96 | 26,290.6 | 22,604.7 | +17.83% | 86.5% |

Percent gains are averages of each paired relative difference, so they need not
equal the percentage difference between the two displayed means. The primary
baseline and simulated opponents are weak: they blindly use last year's totals.
For example, the model could obtain Damian Lillard at pick 136 in one 2022-23
simulation. This is not realistic evidence that such bargains would exist in the
user's league. Beating that field does not establish draft quality.

## Concrete failures

| Evaluation season | Model selections that played zero games | Number of model drafts selecting them |
|---|---|---:|
| 2019-20 | Darren Collison | 10/96 |
| 2019-20 | Kevin Durant | 10/96 |
| 2019-20 | DeMarcus Cousins | 8/96 |
| 2023-24 | Carmelo Anthony | **96/96** |

Zero games alone does not imply retirement; it also includes injuries and other
absences. Carmelo's retirement is independently documented above. The bug is
that a player missing from the most recent season can be resurrected from the
older season with a positive games forecast. Draft selection has no independent
retirement/current-roster gate. The same mechanism allowed the Westbrook mock pick.

The model also displays ADP without using it to choose picks, and its legality
checks do not optimize marginal weekly starting-lineup contribution. This test
did not repair or retune those behaviors.

## Data quality and verification

| Season | Prior-stat player pool with historical positions | Excluded for missing prior fantasy positions | Draft cutoff |
|---|---:|---:|---|
| 2019-20 | 658 | 0 | 2019-10-21 |
| 2022-23 | 669 | 28 | 2022-10-17 |
| 2023-24 | 657 | 56 | 2023-10-23 |
| 2024-25 | 613 | 48 | 2024-10-21 |

Missing-position exclusions were determined from inputs before drafting, not
from outcomes. Archived PDF team/position columns contain some incorrect values;
only their rank/name fields were used. Positions came from the preceding ESPN
fantasy season and were held fixed. Draft-day eligibility changes are not modeled.
Eight archived names in 2022-23 and five in 2024-25 did not match the prior-games
universe, mostly rookies; the machine-readable summary lists every unmatched name.

ESPN NBA totals were requested with explicit season, regular-season type and no
qualification filter. Returned season, unique athlete IDs, complete pagination,
finite values and every required scoring stat were checked. Missing players were
scored zero only after verifying a complete feed. A separate calculation using
the raw display totals and an independent bitmask lineup optimizer verified all
**1,152 scored roster records**. These records include shared model arms.

All **76 basketball backend tests** pass, including information-leakage rejection,
unchanged decisions under different outcomes, checksum tamper detection, scoring
of zero-game picks, and production top-pick equivalence after a performance-only
early-exit optimization.

Not simulated: daily game congestion, weekly matchups, waivers, streaming, trades,
playoffs, preseason news screening or full numeric preseason projections. The
pandemic-shortened 2019-20 season is reported separately as a stress case.

## Evidence and reproduction

- Strategy under test: `2c349c156a8b82825e0ca241b0f66501751b605f`.
- Protocol commit: `3658985`.
- Evaluation implementation: `c832a38`.
- Decision SHA-256: `44964111691046cfbc262557a4b3337726ba7a02e1955024e1caae80ab0a36bb`.
- [Machine-readable summary, hashes and source URLs](basketball_backtest_summary.json).
- Runtime decisions, complete inputs, raw feeds and scored rosters remain in the
  ignored `basketball/data/backtest/` directory.

```sh
python -m pip install pdfplumber
python -m basketball.backtest prepare
python -m basketball.backtest draft
python -m basketball.backtest score
python -m unittest discover -s tests -p test_basketball_backtest.py -v
```

Primary data sources:
[ESPN NBA statistics](https://www.espn.com/nba/stats),
[2022-23 preseason points sheet](https://g.espncdn.com/s/fbadraftkit/2022-2023/FBA2022CSpts.pdf),
[2024-25 preseason points sheet](https://g.espncdn.com/s/fbadraftkit/2024-25/FBA24ptsCS.pdf).
The JSON summary records the exact season-specific API URLs and PDF checksums.
