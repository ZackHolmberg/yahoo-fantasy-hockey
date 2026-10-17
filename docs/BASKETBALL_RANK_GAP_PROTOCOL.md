# Expert rank minus ESPN rank experiment

This is a retrospective diagnostic, not a new blind holdout. Previous experiments have already read outcomes for these seasons. Freeze this protocol and all decisions before grading the new rules; do not tune rules after seeing these results.

## Question and sign

At each pick calculate `gap = expert_rank - espn_rank`. More negative means the expert ranks a player earlier than ESPN does. Example: expert 20, ESPN 45, gap -25. This measures an ordinal disagreement, not an expected fantasy point surplus or proof the player will survive until the next turn.

## Sources

Use the existing frozen strategy-lab player universes and prior-season statistics, with the league's 16 teams, snake order, 12-player rosters, nine starting slots, scoring and center cap. No present-day availability or target-season statistics enter decisions.

* API diagnostics: seasons ending 2023, 2024, 2025 and 2026. ESPN's season-specific `kona_player_info` STANDARD draft ranks are the market order. Rotoworld's dated preseason points board is the expert source for 2025; the dated ESPN published points boards are the expert source for the other three years. Those three comparisons are between two ESPN lists, not independent analysts. The historical API fields have no verifiable preseason capture/publication timestamp and may have been revised later. Consequently these runs cannot establish an unbiased historical edge.
* Dated published-board comparison: 2025 Rotoworld points rankings versus the dated ESPN published points rankings. Both sources precede the season. This is a comparison of published boards, not an authenticated reconstruction of ESPN draft-room ranks or ADP.

Cache raw responses and record their hashes. Only positive integer STANDARD ranks below 999 enter rank differences. Never assign an artificial rank of 999 to missing players. Report coverage and unmatched ranks.

## Fixed policies and fields

1. `expert_best`: take the legal player with the lowest expert rank.
2. `gap_all`: take the legal player with the most negative gap, across the entire shared ranked universe.
3. `gap_window`: take the most negative gap among legal players with expert ranks from the best legal available rank through that rank + 15 (one 16-team round).

Ties resolve by expert rank, then player ID. If no negative comparable gap exists, gap rules fall back to `expert_best`. If the expert board is exhausted, use the prior-season total-points order, without fabricating a rank gap.

Opponents use the ESPN market board, falling back to prior-season total points. Their pool requires a prior-year appearance or inclusion in either board. Each field is simulated in exact market order and two deterministic Gaussian perturbations with standard deviation 12 ordinal places, seeds 0 and 1. Use identical opponent preferences across paired policies, every one of the 16 draft slots, and all 12 rounds: 48 drafts per policy per comparison, 720 complete leagues overall. Enforce the same roster legality and ability to fill all starters for every team.

Record each target pick's ranks, gap, best expert available, five best available negative gaps, and whether fallback was used. Outcomes must be passed only to a separate grading phase. Lock inputs, decisions, configuration and implementation hashes first.

## Metrics and limits

Compare each rule with its paired `expert_best` draft: mean percentage change in all-roster actual season points and hindsight best legal nine starters, strict paired win rate, zero-game players and 10th/90th percentile starter changes. Negative and positive results are equally publishable. Check all drafted rosters for uniqueness, legality and starter coverage. Save full pick traces locally and publish a compact report plus machine-readable summary.

This does not simulate weekly matchups, daily congestion, injuries as known at each historical pick, waivers or playoffs. Published boards may use different points scoring. A rank-gap strategy may repeatedly select experts' low-ranked sleepers before the elite players; the unrestricted policy deliberately tests that failure mode. Do not deploy a winner based solely on this diagnostic.
