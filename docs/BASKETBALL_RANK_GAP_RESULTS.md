# Expert board minus ESPN rank: retrospective backtest

Completed 720 deterministic 16-team snake drafts across four seasons and five board comparisons. Every draft has 12 rounds and every target draft position is tested in three opponent fields. Rules and sources were committed before grading; all these seasons had already been evaluated in previous work, so this is not a fresh blind test.

Neither gap policy beat best expert available on average in any comparison. In the dated 2024–25 comparison, unrestricted gap reduced starter points by 5.45%; a one-round window reduced them by 1.73%, with a 0.15% improvement in all-roster points. The gap is useful for inspecting disagreements, but these results do not support replacing expert rank with largest-gap selection. For example, the window rule took Kawhi Leonard at pick 25 (expert 27, ESPN 92) while Alperen Sengun (expert 15) remained available. Current availability is a separate requirement and does not turn ordinal disagreement into predicted points.

`gap = expert rank - ESPN rank`: more negative means the expert values the player earlier. Expert 20 versus ESPN 45 gives -25. The gap measures disagreement, not fantasy points or certainty that the player remains available.

## Results

Changes are paired against taking the best available expert-ranked player in the same slot and field. Starter points mean the hindsight best legal nine-player lineup scored for the whole season; roster points count all 12 players. Wins are strict starter-point wins against the paired baseline, not fantasy league championships. Each row contains 48 drafts.

| Season / ESPN source | Expert source | Rule | Starter change | Roster change | Paired wins | Starter P10 / P90 |
|---|---|---|---:|---:|---:|---:|
| 2022–23 / API* | ESPN PDF | Largest gap, unrestricted | -24.94% | -21.38% | 0.0% | -29.9% / -19.6% |
| 2022–23 / API* | ESPN PDF | Largest gap, one-round window | -3.08% | -1.59% | 33.3% | -12.0% / +7.5% |
| 2023–24 / API* | ESPN PDF | Largest gap, unrestricted | -50.88% | -54.19% | 0.0% | -54.0% / -47.8% |
| 2023–24 / API* | ESPN PDF | Largest gap, one-round window | -8.85% | -10.38% | 16.7% | -17.2% / +3.0% |
| 2024–25 / API* | Rotoworld | Largest gap, unrestricted | -31.24% | -34.49% | 0.0% | -38.9% / -23.9% |
| 2024–25 / API* | Rotoworld | Largest gap, one-round window | -11.84% | -14.16% | 6.2% | -17.3% / -5.8% |
| 2024–25 / published PDF | Rotoworld | Largest gap, unrestricted | -5.45% | -3.86% | 29.2% | -12.5% / +3.3% |
| 2024–25 / published PDF | Rotoworld | Largest gap, one-round window | -1.73% | +0.15% | 41.7% | -13.1% / +10.0% |
| 2025–26 / API* | ESPN PDF | Largest gap, unrestricted | -47.65% | -49.92% | 0.0% | -57.4% / -39.4% |
| 2025–26 / API* | ESPN PDF | Largest gap, one-round window | -12.13% | -13.04% | 8.3% | -25.0% / -0.3% |

*API rows are diagnostics: historical STANDARD draft ranks were fetched after the seasons and have no verified preseason timestamp. They may contain revisions. Three API comparisons also use ESPN for both the expert and market lists. The dated 2024–25 Rotoworld-versus-ESPN comparison avoids that API timing ambiguity, but its ESPN list is a published expert sheet, not a historical draft-room snapshot or ADP. Do not treat these runs as evidence of a reliable trading edge.*

## Decisions at each pick

The full local `basketball/data/rank-gap/decisions.json` records the selected player, both ranks, the gap, best expert available, five largest legal negative gaps and fallback status at every target pick (8,640 picks total). Missing ranks remain missing and never become artificial bargains.

This preselected example is the dated 2024–25 comparison, draft slot 8, exact ESPN published order for opponents, one-round gap window. It is an illustration, not the best-performing run.

| Overall pick | Player chosen | Expert | ESPN | Gap | Best expert available |
|---:|---|---:|---:|---:|---|
| 8 | LaMelo Ball | 8 | 24 | -16 | Joel Embiid (4) |
| 25 | Kawhi Leonard | 27 | 92 | -65 | Alperen Sengun (15) |
| 40 | Kyle Kuzma | 35 | 56 | -21 | Jamal Murray (23) |
| 57 | Nic Claxton | 43 | 74 | -31 | Nic Claxton (43) |
| 72 | Deni Avdija | 63 | 106 | -43 | Derrick White (57) |
| 89 | Tyus Jones | 74 | 105 | -31 | RJ Barrett (62) |
| 104 | Ivica Zubac | 82 | 129 | -47 | Russell Westbrook (77) |
| 121 | Jordan Poole | 86 | 131 | -45 | Jordan Poole (86) |
| 136 | Scoot Henderson | 91 | 136 | -45 | Scoot Henderson (91) |
| 153 | Andre Drummond | 95 | — | — | Andre Drummond (95) |
| 168 | Mitchell Robinson | 116 | — | — | Mitchell Robinson (116) |
| 185 | Shaedon Sharpe | 118 | — | — | Shaedon Sharpe (118) |

## Method and checks

All policies enforce the league’s roster constraints and ability to fill starters, including a maximum of four primary centers. Opponents follow the ESPN market order or one of two seeded perturbations (standard deviation 12 places). The baseline takes the best legal expert rank. Unrestricted gap selects the most negative legal gap from the entire shared board. The window rule restricts that search to the best legal expert rank through that rank + 15. Gap policies fall back to the baseline when no negative comparable gap exists; an exhausted board uses previous-season points. No target-season outcome is supplied to draft decisions. No current availability checks are applied retroactively.

Independent checks verified 720 target records (240 unique rosters) from raw ESPN display totals using a separate slot-bitmask lineup optimizer. All 720 full leagues passed unique-player, roster-size and center-cap checks; trace gap arithmetic was checked. Seven focused backend tests cover sign, window limits, missing ranks, legality, deterministic picks, outcome isolation and lock tampering.

Decision SHA-256: `ffde2be6686fd8d656a039fe66d911c0d47017221a36d4a1bf274bbb133e72a6`. Input and implementation hashes, source links, source hashes, coverage and all aggregate metrics are in [the machine-readable summary](basketball_rank_gap_summary.json). Raw API payloads, full source packs, decisions and scored rows remain in gitignored runtime data.

## Reproduce

Prepare the source packs with `basketball.strategy_lab prepare` first if they are absent. These commands perform public reads and local simulations; they do not submit draft picks.

```sh
python -m basketball.rank_gap prepare
python -m basketball.rank_gap draft
python -m basketball.rank_gap score
python -m unittest discover -s tests -p test_basketball_rank_gap.py -v
```

The optional `python -m basketball.rank_gap current` compares the separately parsed 2026–27 Rotoworld points board with the cached practice draft’s ESPN STANDARD ranks. It records missing matches rather than inventing ranks, is not scored against past seasons, and is explicitly marked as a cached advisory snapshot with availability unchecked. Use `--expert-board` and `--draft-init` to supply newer source files.

See [the preregistered protocol](BASKETBALL_RANK_GAP_PROTOCOL.md) and [the earlier strategy experiment](BASKETBALL_STRATEGY_RESULTS.md). Neither weekly head-to-head results, daily lineup congestion, waiver replacement nor championship probabilities are simulated. Different publishers may assume different points scoring.
