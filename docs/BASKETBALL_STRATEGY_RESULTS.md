# Enriched basketball draft strategy results

Frozen development selection: **roster_fit**. Selection used 2022-23 through 2024-25 only; 2025-26 was scored afterward.

Completed **6,048 simulated 16-team drafts** across four seasons, all 16 slots, three opponent families and three preference seeds. Ten common strategies and two 2024-25-only diagnostics were registered before scoring.

## Main comparison

Values below are mean paired percentage changes in best fixed legal starting-nine season points against the archived ESPN expert-rank policy. Only expert/mixed opponent fields are included. Each season column has 96 correlated comparisons per policy.

| Strategy | 2022-23 development | 2023-24 development | 2024-25 development | 2025-26 chronological test |
|---|---:|---:|---:|---:|
| prior_total | -6.52% | -12.79% | -11.36% | -51.25% |
| history_blend | -17.68% | -15.88% | -9.40% | -49.24% |
| recent_gate | -17.68% | -15.97% | -7.81% | -49.24% |
| per_game | -10.65% | -11.19% | -15.06% | -38.69% |
| durability | -4.27% | -8.45% | -10.20% | -43.90% |
| expert_rank | +0.00% | +0.00% | +0.00% | +0.00% |
| rank_blend | +1.17% | -10.11% | +4.74% | -11.17% |
| risk_blend | +6.60% | -2.35% | -1.78% | -8.49% |
| **roster_fit (selected)** | +7.02% | -2.30% | -1.83% | -8.48% |
| market_patience | +5.65% | -1.45% | -1.32% | -7.54% |

**The selected strategy failed the chronological test and should not be deployed automatically.** The expert-rank baseline beat every tested common alternative on the held-out starting-nine metric.

The selected strategy had a development mean gain of +0.96% and a held-out mean gain of -8.48%. Its held-out paired win rate was 39.6%; mean finish by this static scoring proxy was 7.08/16. These are not real head-to-head win or title probabilities.

The held-out winner is reported below as a diagnostic, not substituted for the development-selected strategy. No parameters were tuned on held-out outcomes.

## Field sensitivity on 2025-26

| Strategy | Expert field | Mixed field | Prior-total stress field |
|---|---:|---:|---:|
| prior_total | -46.59% | -55.91% | -31.25% |
| history_blend | -48.32% | -50.16% | -16.34% |
| recent_gate | -48.32% | -50.16% | -16.34% |
| per_game | -57.85% | -19.53% | -11.08% |
| durability | -46.36% | -41.43% | -13.03% |
| expert_rank | +0.00% | +0.00% | +0.00% |
| rank_blend | -20.60% | -1.74% | -4.95% |
| risk_blend | -19.94% | +2.96% | +2.03% |
| roster_fit | -20.39% | +3.43% | -4.06% |
| market_patience | -18.11% | +3.03% | +2.03% |

## Independent 2024-25 diagnostics

| Policy | Starting-nine gain vs ESPN | Full-roster gain vs ESPN |
|---|---:|---:|
| consensus_rank | +1.23% | +1.59% |
| projection_total | +0.70% | +5.98% |

These policies have only one covered season and could not win development selection. Projections were converted using the actual league weights; they were not treated as NBA points or Yahoo fantasy values.

## What changed in the data

- Added dated ESPN points sheets for 2023-24 and 2025-26 to the previously recovered 2022-23 and 2024-25 sheets. Published ranks are not actual ADP.
- Added Rotoworld preseason October 2024 points ranks and numeric preseason forecasts. 286 projection rows were extracted; 283 match the input universe. Unmatched names: bubcarrington, codywilliams, daltonknecht.
- Published rookies and returning players without NBA history are included. Rank-neighbor priors are explicitly imputed, not presented as recovered projections.
- Historical veteran positions come from the preceding fantasy season. Published positions are used only where prior eligibility is missing; the ESPN sheets have some incorrect team/position columns. Team columns are ignored.
- Excluded the live Razzball projection page: its 2023-24 heading coexists with later team assignments. Current FantasyPros/Hashtag ADP pages were not relabeled historical.

| Season | Pool | ESPN ranked | No prior NBA history | Published-position fallback | Missing-position exclusions |
|---|---:|---:|---:|---:|---:|
| 2022-23 | 677 | 200 | 8 | 7 | 28 |
| 2023-24 | 667 | 200 | 10 | 9 | 56 |
| 2024-25 | 625 | 150 | 12 | 12 | 48 |
| 2025-26 | 655 | 150 | 5 | 5 | 44 |

## Player availability and downside

| Strategy | Development zero-game picks/team | Test zero-game picks/team | Test lower-decile paired starting-nine gain |
|---|---:|---:|---:|
| prior_total | 0.68 | 3.86 | -63.02% |
| history_blend | 0.85 | 3.52 | -58.95% |
| recent_gate | 0.67 | 3.52 | -58.95% |
| per_game | 0.89 | 3.70 | -64.15% |
| durability | 0.60 | 4.02 | -54.88% |
| expert_rank | 0.02 | 0.19 | +0.00% |
| rank_blend | 0.49 | 1.38 | -29.04% |
| risk_blend | 0.33 | 1.52 | -30.06% |
| roster_fit | 0.35 | 1.47 | -30.06% |
| market_patience | 0.34 | 1.44 | -27.91% |

In the 96 held-out expert/mixed-field drafts, history_blend selected Tyrese Haliburton, Damian Lillard and Fred VanVleet in all 96 drafts each; all three were absent from the verified complete regular-season outcome feed. The selected roster_fit policy still selected Haliburton 46 times, Lillard 46, Kyrie Irving 27 and VanVleet 20. Their prior-year production remained attractive to the history component despite their absence from the published top 150. This explains much of the held-out collapse.

The recent-games/published-rank screen is a heuristic. It removes stale players missing the latest year, while allowing published returning players, but it cannot reliably catch a newly retired player who played last season. A current authoritative eligibility/news check is still required. Unpublished unsigned veterans and long-term injuries remain possible mistakes.

## Current-season enrichment

Recovered an independent 2026-27 Rotoworld top-200 points board, published before the upcoming draft, and retained its source/checksum locally. It never enters the historical experiment. The prior practice roster compares as follows:

| Practice pick | Current independent points rank |
|---|---:|
| Jayson Tatum | 7 |
| Alperen Sengun | 16 |
| Kon Knueppel | 84 |
| Tyler Herro | 50 |
| Joel Embiid | 43 |
| Jalen Green | 93 |
| RJ Barrett | 176 |
| Quentin Grimes | 139 |
| Sandro Mamukelashvili | 118 |
| Jay Huff | 194 |
| Russell Westbrook | Outside top 200 |
| Cam Spencer | 169 |

These are expert ranks, not ADP. Absence from the top 200 is not proof of retirement. This source can help review reaches and omitted prospects, but it has not been wired into unattended drafting.

## Verification and practical limits

- Independent raw display totals and a separate slot-bitmask optimizer verified all **6,048 target-roster records** (3,368 unique season/roster combinations).
- Ten targeted backend tests pass, covering legality/caps, lookahead behavior, rookie handling, future-data rejection, tamper checks and freezing selection before held-out outcome access. A real-input mixed-field market-patience draft was repeated twice and produced identical roster checksums.
- Every decision/input/source is hashed before scoring. The old production model and earlier backtest remain unchanged. The history_blend arm is a total-order ablation, not an exact replay of the production positional-value policy.
- PDF dates are before each cutoff, and source bytes are retained. Retrieval today plus PDF metadata is not cryptographic proof that the publisher never revised an archive.
- Fixed starting nine is selected using outcomes during grading only. It is an optimistic proxy; daily lineup congestion, schedules, weekly matchups, acquisitions, injury replacement and fantasy playoffs are absent.
- Opponents are reproducible expert/rank preference models, not measured human ADP. Expert lists end at 150/200 and use a prior-points tail. Seeds/slots within a season are correlated.
- Three development years already appeared in earlier work. Only 2025-26 is a new algorithm holdout; the operator may know historical events. One holdout season is insufficient evidence of a durable edge.
- No live ESPN picks, roster moves, trades or league writes were used. No strategy was automatically deployed.

## Reproduce

An initial unscored decision set was discarded after a projection-header parsing bug was found. The corrected parser matches full team names, has a regression test for P.J. Washington, and all 6,048 decisions were regenerated before any strategy grading. No outcome-based player exclusions or parameter changes were made.

```sh
python -m pip install pdfplumber
python -m basketball.strategy_lab prepare
python -m basketball.strategy_lab draft
python -m basketball.strategy_lab develop
python -m basketball.strategy_lab test
python -m unittest discover -s tests -p test_basketball_strategy_lab.py -v
```

Decision SHA-256: `38650f9cac895a8f984fd21cd703feb2cb5b7f3e36a68f86720fdc81d305fd38`.
Selection SHA-256: `67abcb67e0cca91806d6bda56dd5041051570f696fa35c89a2ed31343ae9ae17`.

[Registered protocol](BASKETBALL_STRATEGY_PROTOCOL.md) | [Machine-readable summary](basketball_strategy_summary.json)

Source files:
- 2023: [FBA2022CSpts.pdf](https://g.espncdn.com/s/fbadraftkit/2022-2023/FBA2022CSpts.pdf); PDF dates 20221012, 20221012.
- 2024: [FBA2024top200PTS.pdf](https://g.espncdn.com/s/fbadraftkit/2023-2024/FBA2024top200PTS.pdf); PDF dates 20231020, 20231020.
- 2025: [FBA24ptsCS.pdf](https://g.espncdn.com/s/fbadraftkit/2024-25/FBA24ptsCS.pdf); PDF dates 20241018, 20241018.
- 2025: [rotoworld-2024-25-fantasy-basketball-kit.pdf](https://nbcsports.brightspotcdn.com/03/10/b09f526442aab7ad4db7ba3584ed/rotoworld-2024-25-fantasy-basketball-kit.pdf); PDF dates 20241001, 20241001.
- 2026: [fbacheatsheetPts.pdf](https://g.espncdn.com/s/fbadraftkit/2025-26/fbacheatsheetPts.pdf); PDF dates 20251020, 20251020.
- Current season: [Rotoworld 2026-27 PDF](https://nbcsports.brightspotcdn.com/27/f4/76d4f84f47558c1d78522de7270e/rotoworld-2026-27-fantasy-basketball-kit-v2.pdf).
