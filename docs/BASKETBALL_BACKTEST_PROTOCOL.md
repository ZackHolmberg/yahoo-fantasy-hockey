# Historical basketball draft test: locked protocol

Registered October 17, 2026, before running/scoring the simulations. The strategy
under test is commit `2c349c156a8b82825e0ca241b0f66501751b605f`; no outcome-based
tuning is permitted in this run. This is a chronological historical holdout, not
a claim that the human operator has never seen historical NBA results.

## Scope and information boundary

- Evaluate seasons ending 2023, 2024 and 2025; add 2020 as a stale-player/retirement
  stress case. ESPN years denote the year a season ends.
- Use the user's 16-team, 12-player snake format, nine starting slots, four-primary-
  center cap and exact points weights from basketball/league.json.
- The production Model and draft board receive only totals from the preceding
  two completed regular seasons. Historical ESPN fantasy position eligibility
  is taken from the preceding season, never today's profile.
- No target-season games, stats, current ADP, current injuries/team assignments,
  or hindsight player exclusions enter draft selection. Names/IDs only may be
  used for identity matching. Outcome stats are passed only to the evaluator.
- Numeric preseason projections with reliable capture timestamps were not
  recovered. This tests the existing history fallback, not the complete ESPN
  projection-assisted production strategy. Missing rookie priors are a limitation.

## Comparisons and draft simulation

- Primary baseline: select by the previous season's total points, subject to the
  same roster/position and future-starter-coverage constraints as the model.
- Simulate each of the 16 draft positions against opponents using that baseline.
  Run an ordered opponent board and five independently seeded noisy boards
  (Gaussian rank noise, standard deviation eight places). Both arms of a pair
  receive the identical seed and opponent preference board.
- Secondary baseline where recovered: archived ESPN preseason points rank,
  with unlisted players ordered after listed players by previous-season points.
  Label the 2024-25 sheet's 150-player cutoff and the hybrid tail explicitly.
  Do not call these published ranks ADP or archived numeric projections.
- The player universe is players appearing in either input season. Retired,
  unsigned and injured players are not removed using future results. Thus this
  intentionally measures the stale-history failure exposed by Westbrook; it
  cannot independently validate draft-day roster/news screening.
- Save all draft decisions and their SHA-256 digest before evaluating outcomes.
  Re-running with changed inputs/decisions invalidates that digest.

## Metrics and interpretation

- Primary metric: actual regular-season points summed across the 12 drafted
  players. Report paired differences, relative differences and paired win rate.
- Secondary metric: points of the best fixed legal nine-player starting lineup,
  chosen only during scoring. This is an optimistic season-total proxy, not a
  daily lineup or head-to-head championship simulation.
- Report zero-game selections, low-game selections and the selected players.
  Missing players in a verified complete outcome feed receive zero games/points;
  missing or partial feeds cause scoring to fail.
- No waivers, trades, streaming, NBA playoff games, historical fantasy schedules,
  game-by-game lineup congestion or calibrated opponent behavior are simulated.
  Seeds/slots within a season are correlated; do not advertise them as independent
  real leagues or claim a championship probability.
- Publish losses and data limitations. Passing execution tests or beating the
  weak primary baseline does not establish readiness for the real draft.

ESPN's dated preseason PDFs are retained with checksums. Actual totals come from
ESPN's NBA statistics endpoint with explicit season and regular-season filters;
pagination and returned season are checked. Data stays in ignored runtime files.
