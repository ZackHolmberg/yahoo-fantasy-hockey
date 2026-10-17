# Expanded basketball ranking and backtest data

Collected and validated October 17, 2026. There are now **12 historical points-ranking boards (1,600 published entries) across six completed seasons**, plus **three current 2026–27 boards (550 entries)** from independent publisher families. These are data inputs for further experiments; no new source was declared better and no new strategy outcomes were scored.

## Historical points boards

| Season | Board | Published entries | Matched / usable in player pool | Notes |
|---|---|---:|---:|---|
| 2017–18 | [ESPN — published expert order](https://www.espn.com/graphics/2016/1014/top150points1012.pdf) | 150 | 150 / 150 | New historical season; dated points PDF |
| 2018–19 | [ESPN — published expert order](https://www.espn.com/graphics/2016/1014/2018fantasyhoopscheatsheetsptsrk.pdf) | 150 | 150 / 150 | New historical season; dated points PDF |
| 2022–23 | [ESPN — published expert order](https://g.espncdn.com/s/fbadraftkit/2022-2023/FBA2022CSpts.pdf) | 200 | 200 / 200 |  |
| 2022–23 | [RotoWire — published expert order](https://www.rotowire.com/basketball/article/fantasy-basketball-cheat-sheet-2022-23-top-players-sleepers-busts-66579) | 50 | 50 / 50 | Public top 50 points list; full customized list requires subscription |
| 2023–24 | [ESPN — published expert order](https://g.espncdn.com/s/fbadraftkit/2023-2024/FBA2024top200PTS.pdf) | 200 | 200 / 200 |  |
| 2024–25 | [ESPN — published expert order](https://g.espncdn.com/s/fbadraftkit/2024-25/FBA24ptsCS.pdf) | 150 | 150 / 150 |  |
| 2024–25 | [RotoWire — published expert order](https://www.rotowire.com/basketball/article/fantasy-basketball-points-league-rankings-2024-projections-85939) | 50 | 50 / 50 | Public top 50; projections omit shooting attempts/makes needed for custom scoring |
| 2024–25 | [Rotoworld — published expert order](https://nbcsports.brightspotcdn.com/03/10/b09f526442aab7ad4db7ba3584ed/rotoworld-2024-25-fantasy-basketball-kit.pdf) | 200 | 200 / 200 |  |
| 2025–26 | [ESPN — published expert order](https://g.espncdn.com/s/fbadraftkit/2025-26/fbacheatsheetPts.pdf) | 150 | 149 / 149 |  |
| 2025–26 | [RotoWire — projected points per game](https://www.rotowire.com/basketball/article/fantasy-basketball-points-league-rankings-2025-26-nba-projections-95771) | 100 | 100 / 100 | Public top 100; native scoring forecast, no complete custom-scoring stat line |
| 2025–26 | [RotoWire — projected total points](https://www.rotowire.com/basketball/article/fantasy-basketball-points-league-rankings-2025-26-nba-projections-95771) | 100 | 100 / 100 | Public top 100; native scoring forecast, no complete custom-scoring stat line |
| 2025–26 | [RotoWire — published expert order (July snapshot on NBA.com)](https://www.nba.com/news/nba-fantasy-early-top-100-fantasy-rankings-for-2025-26-points-leagues) | 100 | 100 / 100 | Early July snapshot; same publisher family as RotoWire, not an independent vote |

The new independent historical points source is RotoWire: top-50 boards for 2022–23 and 2024–25, and top-100 total-points/per-game boards for 2025–26. The July 2025 NBA.com board is a different dated snapshot by RotoWire, not another independent expert. ESPN and Rotoworld inputs from the earlier experiment are retained in the unified catalog. The two older ESPN PDFs add 2017–18 and 2018–19 to the four previously prepared ranking seasons.

## Current boards captured before this league’s draft

| Publisher | Entries | Latest date evidence | Source |
|---|---:|---|---|
| Rotoworld | 200 | 2026-10-05 | [Published points board](https://nbcsports.brightspotcdn.com/27/f4/76d4f84f47558c1d78522de7270e/rotoworld-2026-27-fantasy-basketball-kit-v2.pdf) |
| RotoWire | 150 | 2026-10-15 | [Published points board](https://www.nba.com/news/nba-fantasy-top-150-for-2026-27-points-leagues) |
| FantraxHQ | 200 | 2026-10-12 | [Published points board](https://fantraxhq.com/2026-27-fantasy-basketball-points-league-rankings-updated/) |

These are three publisher families: Rotoworld, RotoWire and FantraxHQ. NBA.com hosts the RotoWire list. The list order is retained exactly; team columns/narratives are not treated as roster authority. Current team membership and availability still require the separate live checks. Historical backtest input construction excludes these current boards. Their source hashes and capture times preserve a prospective starting point for evaluation after 2026–27.

## Prior statistics and identity coverage

The public ESPN regular-season statistics cache now spans seasons ending 2016 through 2026 (2015–16 through 2025–26). Input construction uses only the two seasons preceding each target season, while target-season fantasy metadata supplies names and IDs only. It does not import target-season status, teams, positions or statistics. Existing raw-data validation checks season/type, complete pagination, unique athlete IDs and finite scoring fields. These are season totals; daily player game logs have not been added.

| Target season ending | Player pool | Source boards | Published position fallbacks | Players excluded without historical/published position | Unresolved ranking names |
|---:|---:|---:|---:|---:|---:|
| 2018 | 582 | 1 | 5 | 0 | 0 |
| 2019 | 632 | 1 | 0 | 2 | 0 |
| 2023 | 677 | 2 | 7 | 28 | 0 |
| 2024 | 667 | 1 | 9 | 56 | 0 |
| 2025 | 625 | 3 | 12 | 48 | 0 |
| 2026 | 654 | 4 | 4 | 44 | 1 |

Several historical fantasy lists contain duplicate identities for the same player name. A unique prior NBA-statistics identity resolves those without consulting future performance. RotoWire’s three abbreviated 2022–23 names have explicit, source-specific aliases. Egor Demin has two target-season fantasy IDs and no prior NBA identity: the new 2025–26 input leaves his ESPN rank unresolved rather than guessing. Consequently that input uses 149 of the 150 ESPN ranks. Other prepared boards have complete identity matches for their published coverage.

## Quarantined or incomplete sources

* [FantraxHQ 2019–20 points top 150](https://www.fantraxhq.com/2019-20-top-150-fantasy-basketball-points-league-rankings/) was modified October 27/28, 2019, after opening night. Its 150 rows are stored as diagnostic data and excluded from clean historical inputs. A dated pre-draft archive is still needed.
* [FantraxHQ 2021–22 consensus](https://fantraxhq.com/2021-22-fantasy-basketball-rankings/) has 145 published rows, including ties and four analysts’ columns. It is stored separately as category/format-unspecified data and excluded from points-board inputs.
* [RotoBaller’s 2023–24 points article](https://www.rotoballer.com/alex-burns-2023-2024-fantasy-basketball-points-leagues-rankings) is dated preseason, but its top 150 live in a FantasyPros widget. The captured widget contains only a script/configuration shell. No complete dated board was recovered, so it is not counted as a ranking dataset.
* RotoWire’s historical ADP page was found, but no timestamp-verified historical ADP dataset was imported. The data above do not repair the earlier experiment’s lack of real ADP.
* The new RotoWire numerical forecasts use the publisher’s scoring and omit shooting makes/attempts needed for this league. Available columns are retained as native forecasts. No missing statistics, extra player ranks or custom fantasy-point forecasts are invented. Existing full Rotoworld 2024–25 numeric projections remain in the earlier strategy dataset.
* Clean points boards for 2019–20 through 2021–22 remain a gap; the older category or revised articles are not substituted under a points label.

## Collection and verification

The manifest records publisher family, season, format, rank basis, coverage, parser, source URL and explicit aliases. Collection validates table headers, exact row counts, complete ranks, unique normalized player names and source dates; native tied ranks require an explicit declaration. Article publication and modification timestamps are compared with timezone-aware cutoffs. PDF creation/modification timestamps retain their offsets. Current captures must also precede the league’s October 18 cutoff. Publisher dates and PDF metadata are evidence rather than cryptographic proof of the originally published bytes.

Raw bytes, capture times, URLs and SHA-256 hashes are preserved locally. Reusing a source ID with changed bytes/URL is rejected. Normalized board hashes and original-source hashes are rechecked before building historical inputs. Missing, ambiguous, revised and category sources cannot silently enter points tests.

Eleven targeted backend tests pass. They cover date/offset handling, incomplete boards, duplicate names/ranks, explicit tied ranks, column/title changes, source tampering, target-outcome isolation and prior-position preservation. Real data also completed **12 unscored 16-team drafts (2,304 picks)**, one for each historical source board, with full-roster legality, nine-starter coverage and center-cap checks. Previously matched ESPN ranks agree with the existing frozen strategy dataset; its source files and locks are unchanged. These checks establish input/engine compatibility, not strategy performance.

## Use the data

```sh
python -m pip install pdfplumber
python -m basketball.ranking_library collect
python -m basketball.ranking_library build
python -m unittest discover -s tests -p test_basketball_ranking_library.py -v
```

The manifest is `basketball/ranking_sources.json`. Local artifacts live under gitignored `basketball/data/ranking-library/`: raw source bytes and capture metadata, normalized `boards/<source-id>.json`, `catalog.json`, six `input-<season>.json` packs, `inputs-summary.json` and unscored compatibility checks. The committed [inventory](basketball_data_inventory.json) contains source URLs, hashes, dates, coverage, input hashes and validation counts without republishing full expert boards.

Each historical pack is compatible with `backtest.input_model` and includes `ranking_boards[source_id]` mappings from ESPN player ID to the original rank. Supply one mapping as the expert board and the baseline mapping as the market board to `rank_gap.ranking`/`rank_gap.simulate`. This allows separate source comparisons while keeping the decision code isolated from outcomes. Do not treat multiple RotoWire snapshots or its total/per-game lists as separate independent votes in a consensus. A new scored experiment must predeclare source coverage, missing-rank tails, publisher weighting, chronological selection and holdouts before scoring.

Production ranking strategy, live bans and availability rules are unchanged. No live league transaction or draft command was sent.
