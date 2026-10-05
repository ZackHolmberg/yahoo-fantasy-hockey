# ESPN team manager: runbook

Claude manages team **Suzuki For Hart** (team 5) in ESPN league **1034056432** ("Leafs suck", 6 teams, H2H points) through the Claude in Chrome extension. `scripts/daily_run.sh espn` runs this headless every day (launchd, see bottom). The Yahoo league has its own runbook, `docs/MANAGER.md`; the safety rules there apply here too.

## League facts that drive everything
- **Scoring:** skaters PTS 1, PIM 0.5, PPP 1, SHP 1, GWG 1, SOG 0.1, HIT 0.1. Goalies W 3, SO 6 (no saves, no GA). Rankings: `espn/data/rankings.csv` (`LEAGUE=espn python3 project.py`, run from `espn/`).
- **Roster:** 12 F (any forward), 6 D, 2 G, 4 bench, 2 IR. 24 players.
- **Lineups lock weekly**, at the first game of each Mon-Sun week. Once the week's first game starts, the lineup is set for the week. So the lineup that matters is the one in place before Monday's first game.
- **Acquisitions:** waivers (1 day), max **7 per matchup week**, no season limit. A player added mid-week can only enter the lineup next week.
- **Trades:** no review period, deadline Feb 26, 2027.

## Authority (set by the owner, 2026-09-30: same as Yahoo)
| Action | Without asking | Needs owner's OK |
|---|---|---|
| Set the weekly lineup, move players to/from IR | yes | |
| Add/drop or waiver claim tagged `AUTO-OK` by `manage.py --league espn eval` | yes, within `espn/data/manager_rules.json` | |
| Any other add/drop (`ASK`, unranked player, goalie swap, dropping a protected player) | | yes |
| Trade proposals, accepting/rejecting trades | | yes, always |
| League settings, messages/chat, anything outside our team pages | never | |

Guardrails (`espn/data/manager_rules.json`): at most 4 auto adds per week (league max 7). A move needs at least +8 rest-of-season FP (ESPN totals run ~1/3 of Yahoo's). Protected players are never auto-dropped. Goalie swaps always ask. Keep at least 2 healthy goalies.

## Each run
The scripts do the reading and the math; you act on their report. Don't re-derive what the report already decided.
1. **Report, no browser:** `python3 manage.py --league espn report --fetch`. It reads ESPN's API with the owner's cookies (`espn/data/espn_auth.json`, gitignored), syncs the roster, and prints:
   - **ACTIONS:** the week's lineup changes (Sunday runs plan next week; Monday runs plan this week before the lock), IR moves, `AUTO-OK` add/drops.
   - **ASK OWNER**, **FYI**, and a **TEXT DRAFT**.
   - Claims from the last 7 days are never suggested twice.
   - If it says the cookies are missing, expired or refused: text the owner once ("ESPN: please re-copy espn_s2/SWID into espn/data/espn_auth.json") and fall back to step 2.
2. **Fallback read (only if step 1 failed):** open a new tab on `https://fantasy.espn.com/hockey/team?leagueId=1034056432&teamId=5`. If it shows a login page, stop and text the owner. Never enter credentials. Read `scripts/espn_read.js` and run its contents with the javascript tool. If it answers "N chunks", call `window.__fhChunk(0)` ... `window.__fhChunk(N-1)`, then run `python3 manage.py --league espn report '<chunk0>' '<chunk1>' ...` with every chunk verbatim and in order.
3. **Act** (Chrome only when ACTIONS isn't empty): do each ACTION on ESPN's pages (My Team → Move; Players → Add or claim). Verify name, team and position before clicking. For an `AUTO-OK` add/drop, run the `manage.py --league espn acq ... --auto` command the report prints, right after the claim goes in.
4. **Verify:** run step 1 again. ACTIONS should now be empty. If something won't go away (the lineup is already locked, IR is full), log why. Don't loop.
5. **Trades** (Monday only): look for teams with surplus where we're thin. Draft proposals only when the model shows value for both sides. **Never send them:** list them for the owner.
6. **Report:** `python3 manage.py --league espn log "..."` (what you did, plus ASK items numbered E1, E2... as the report says). Then send the TEXT DRAFT with `scripts/imessage_send.sh "..."`, edited to match what actually happened. If the draft says none, don't text.

## Owner replies
Replies come through the same iMessage poller as Yahoo. A reply about E-numbered items, or one that says "ESPN", belongs to this league. If it's ambiguous which league the owner means, text back asking.

## Safety
- Verify name, team and position before any add/drop click. ESPN has the same duplicate names as Yahoo (two Elias Petterssons, two Sebastian Ahos).
- The ESPN API reads in `espn_read.js` are read-only. Make every change through the normal ESPN pages. Never script write calls to the API.
- If the browser tools error twice in a row, stop, log, and text the owner.

## Schedule
- `scripts/daily_auto.py espn` at 10:30 ET daily: report, then `espn_bot.py apply` for any ACTIONS (no Claude) (`~/Library/LaunchAgents/com.zackholmberg.fantasyhockey.espn.plist`), plus Sunday 21:00 so the lineup is set the night before the Monday lock. Logs: `data/run_logs/<date>_espn.log`. Uses the same run lock as the Yahoo runs.
- Pause: `launchctl bootout gui/501/com.zackholmberg.fantasyhockey.espn`.
