# Expert quality with market timing: fixed retrospective protocol

Written before generating or grading the hybrid decisions. Previous source-test
outcomes are already known; this is a retrospective extension, not a new blind
holdout or evidence of a uniquely optimal strategy.

The quality order is either the primary RotoWire board or the existing
one-vote-per-publisher consensus. Published prefixes, ESPN completion of missing
ranks, common player pools and prior-season tail completion are unchanged from
the source comparison. Never label a completed ordinal as a published rank.

At each turn compare the best legal expert player with legal players no more
than seven completed quality-order places below that player. For each candidate,
remove the intervening selections before our next snake turn under six fixed
public-order scenarios: ESPN; expert; 75/25 ESPN/expert; 50/50 ESPN/expert; and two
ESPN orders with fixed player-ID hash jitter uniformly spanning -12 to +12 places.
These are demand approximations: they do not know opponents' actual preference
orders and do not simulate their positional constraints. Our current and next
selection must pass the actual roster caps and ability to fill starters.

Maximize the mean sum of `-log(completed quality ordinal)` for our current and
next selection. This is a rank preference utility, not expected fantasy points.
Equal utilities choose the better expert player. Final or consecutive picks take
the best expert first. If every forecast lacks a legal next selection, fall back
to expert-first. Personal bans exclude our choices, including forecast next
choices, but never remove a player from opponent forecasts. Scenario survival
counts are sensitivity descriptions, never calibrated probabilities or ADP.

No parameter sweep or retrospective parameter adjustment is allowed in this
experiment. The eight-place window, utility and six scenarios are fixed before
grading. This rule differs from the previous failed history-blend timing policy:
it uses independent expert quality, a bounded window and multiple public demand
orders. A better result is not presumed.

Use the already locked source-test inputs and baseline decisions for seasons
ending 2023, 2025 and 2026, the three years with independent points boards. For
each year, both original opponent fields (ESPN and publisher consensus), original
exact/noisy seeds (-1, 0, 1), and all 16 snake slots: generate two hybrid policies,
576 new full 16-team drafts. Compare with the same source's greedy expert policy,
consensus greedy and ESPN: 1,440 total paired cases including reused baselines.
All 12 selections and full league rosters remain unique and legal. Use the same
opponent preference generation as the source test. Forecasts cannot access those
hidden opponent preference lists.

Lock code hashes, protocol, inputs, baseline evidence, config and decisions and
commit the lock before reading target-year outcomes. Grade actual custom league
points, hindsight best fixed starting nine, full 12-player totals, zero-game
picks and under-25-game picks. Show paired gains against ESPN and against the
matching greedy expert policy, per year and field, and equal-year averages.
Retain pick traces with candidate comparisons and deferred favorites.

Limitations remain: incomplete historical expert prefixes; current metadata
position fallbacks; limited source years; expert scoring differs from this custom
league; season totals rather than weekly scheduling, waivers or championships.
No default live strategy switch or draft submission is part of this experiment.
Provide an explicitly selected read-only hybrid advisor using current verified
source files; current injury/roster verification is a separate existing gate.
