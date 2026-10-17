# Enriched draft strategy experiment

Registered October 17, 2026 before generating the new decisions or inspecting
2025-26 outcome totals. Existing 2022-23 through 2024-25 results are already known:
those are retrospective development seasons, not fresh blind holdouts. Season
ending 2026 is the chronological test. This is an algorithm information boundary,
not a claim that the operator has no historical knowledge.

## Inputs and sources

Use prior two complete regular-season totals, historical prior-season fantasy
positions, and dated ESPN preseason points sheets for seasons ending 2023-2026.
Use Rotoworld's October 2024 PDF for an independent 2024-25 points ranking and
numeric projections. Confirm PDF modification/creation dates precede each cutoff;
retain source bytes, metadata and SHA-256. Archived files retrieved today are not
cryptographically proven original captures, so disclose that provenance limit.

Include published rookies and returning players even without prior NBA games.
IDs/names may come from historical fantasy player lists, but no target-season
stats, injuries, ownership, positions or team metadata are used. Known veterans
retain previous-season positions. Players missing prior eligibility may use the
published sheet's position; ignore its erroneous team columns. Record that fallback.
Numeric projections are used only for 2024-25; no current projection is relabeled
as historical. A mislabeled Razzball page with post-2023 team assignments is excluded.
No reliable historical actual ADP was recovered; expert ranks are a market proxy,
not ADP. No paywall bypass or Firecrawl is used.

## Fixed strategies, without outcome-based parameter tuning

1. `prior_total`: last season's total fantasy points.
2. `history_blend`: the existing two-season per-game/games blend, total-points order
   without the production positional replacement heuristic (explicit ablation).
3. `recent_gate`: same blend, but exclude players with neither last-season NBA
   games nor a preseason rank. This cannot catch every newly retired player.
4. `per_game`: screened blended FP/game, ignoring expected missed games.
5. `durability`: screened FP/game times conservative games forecast:
   0.50 latest GP + 0.25 older GP + 0.25*65; absent years count zero. Published
   players without any history receive a rank-neighbor estimate and 65 games.
6. `expert_rank`: ESPN ranks, then screened prior-points tail. For 2024-25
   `consensus_rank` additionally averages ESPN and Rotoworld ranks.
7. `rank_blend`: equal-weight ordinal blend of historical total rank and expert rank.
8. `risk_blend`: equal-weight ordinal blend of durability value rank and expert rank.
9. `roster_fit`: risk-blend points proxy, maximizing the legal fixed starting nine
   plus 0.35 times bench value, evaluated at each pick. Top eight legal candidates.
10. `market_patience`: two-pick lookahead using the risk-blend ordinal score.
   Forecast intervening picks with the public expert order (never the hidden
   random opponent preferences), discount next-pick value by 0.95; top eight
   legal candidates. Last round uses immediate value alone.
11. `projection_total` (2024-25 only): league-scored Rotoworld projected totals,
    with screened historical fallback for missing projections.

Implementation clarification before scoring: a Rotoworld preseason rank also
counts as published evidence for the screen and rookie universe in 2024-25.
Its players missing ESPN's top 150 remain in ESPN's unlisted tail. Roster-fit and
lookahead use ordinal utility `1000 - risk_rank`, not calibrated expected points.
The rank-neighbor fallback uses the independent rank if ESPN has no listed rank.

Use published rank-neighbor historical total medians (ten nearest known players)
only to estimate players without any prior games. This is a declared rookie
imputation, not a recovered numeric projection. Raw history ablations give
zero to players without history. Retired/injured players are never excluded by
looking at target outcomes. All policies enforce league roster/cap/coverage rules.

## Drafts, grading and selection

Use the user's 16-team, 12-player, nine-starter, primary-center-cap-four league and
exact points weights. Each policy drafts from each of 16 slots in three opponent
families: expert-rank, equal expert/prior-rank mix, and prior-total stress field.
Each family has ordered preferences and two seeds with Gaussian rank noise SD12.
Opponents use the same screened pool and fixed preferences in every paired arm.
No actual ADP, human behavior or championship probabilities are claimed.

Lock every input, source-code hash, configuration and selected roster before
outcome fetch/scoring. Preserve old backtest files and production model. Score
all-12 total points, best fixed legal starting-nine points, zero-game picks and
mean league finish. The fixed nine is a hindsight proxy, not daily H2H scoring.
Publish season/field/slot dispersion and losses; seeds/slots are correlated.
No daily congestion, waivers, playoffs or trades are modeled.

Select a single common strategy by its mean season-level paired starting-nine
gain over expert_rank across the three development seasons and expert/mixed
opponents (exclude the weaker prior-only field). Freeze that choice before scoring
2025-26, then report its held-out result and all pre-registered competitors. Do
not tune parameters or select the best held-out performer as the recommended one.
One-season projection/consensus variants are diagnostics and cannot win selection.
Do not deploy an automatic real-draft policy based solely on these proxies.
