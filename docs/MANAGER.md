# Daily team manager: runbook

Claude manages team **Suzuki For Hart** (league 23491) every day through the Claude in Chrome extension, because the Yahoo API is still blocked (see `docs/yahoo_api_notes.md`). `scripts/daily_run.sh` runs this runbook headless twice a day (launchd, see bottom). The owner can also say "manage the team" in any session.

## Authority (set by the owner, 2026-09-23)
| Action | Without asking | Needs owner's OK |
|---|---|---|
| Set daily lineup, bench/start, move players to/from IR/IR+/NA slots | yes | |
| Add/drop or waiver claim tagged `AUTO-OK` by `manage.py eval` | yes, within `data/manager_rules.json` | |
| Any other add/drop (`ASK`, unranked player, goalie swap, dropping a protected player) | | yes |
| Trade proposals, accepting/rejecting trades, trade votes | | yes, always |
| League settings, messages/chat, anything outside our team pages | never | |

Guardrails in `data/manager_rules.json`: at most 3 auto adds per week (league max 5, keeps 2 for injuries and owner-approved moves). A move needs at least +25 rest-of-season FP. Protected players are never auto-dropped. Goalie swaps always ask. Keep at least 2 healthy goalies.

## Each run
1. **Open** a new tab in the Claude tab group: `https://hockey.fantasysports.yahoo.com/hockey/23491/` → My Team. If Yahoo shows a login page, stop and text the owner. Never enter credentials.
2. **Sync roster:** read the roster (name, Yahoo positions, injury status: DTD, O, IR, IR-LT, NA) and run `python3 manage.py roster set "Name|POS|STATUS" ...`.
3. **Injuries:** move any player marked IR/IR-LT (or O, if Yahoo allows it) into an open IR/IR+ slot. That frees a roster spot, so evaluate a pickup in step 5. Leave DTD players on the roster, but don't start them if they're ruled out today.
4. **Lineup for today** (daily lineups; each player locks at his game's start):
   - Start every healthy skater whose team plays today. If more players at a position have games than there are slots, start the higher FP/G (`manage.py roster`). Dual-eligible players (LW,RW) fill whichever slot is open.
   - **G (one slot):** start the goalie who is **confirmed** starting today (check the Yahoo player note / "Starting" tag, or DailyFaceoff starting goalies). If none is confirmed at the morning run, start the likely starter with the best FP/G and re-check at the evening run.
   - League rule: **minimum 2 goalie appearances per week.** By Friday, if the week has fewer than 2, prioritize any confirmed starter.
   - Click Yahoo's "Start Active Players" only if it doesn't bench a better player; otherwise set slots by hand. Save and re-read the page to confirm.
5. **Waivers / free agents:** Players → Available (and Waivers), sort by rank or FP, top ~40 skaters plus the top 10 goalies. Run `python3 manage.py eval "Name|POS|STATUS" ...`.
   - `AUTO-OK`: make the add/drop (or waiver claim), then `python3 manage.py acq "Add" "Drop" --auto`.
   - `ASK`, unranked rookies, or any move you'd make on news the model can't see (a new starting goalie, promotion to the top 6/PP1): don't act; list it for the owner with a one-line reason.
   - The model is preseason. After ~15 games, weigh a player's current-season FP/G on Yahoo too (Yahoo's stats show this league's points). Mention it when current form and the model disagree by a lot.
6. **Trades** (weekly, Monday run only): look for other teams' surplus at positions where we're thin (D is our weakest group). Draft a proposal only when the model shows value for both sides. **Never send it:** list it for the owner.
7. **Report:** append to `data/season_log.md` with `python3 manage.py log "..."`: lineup changes, moves made, and pending questions for the owner (number them: `Q1`, `Q2`, ...). Then text the owner with `scripts/imessage_send.sh "..."`:
   - **Text only when there's something to say:** a move was made, a decision is needed, or something broke. A quiet lineup-only day gets no text.
   - Keep it short and phone-readable. For decisions, give each numbered option with a one-line reason so the owner can reply "yes Q1" or "no".

## Owner replies (iMessage)
`scripts/imessage_poll.py` (launchd, every 2 min) starts a `reply` run when the owner texts from their own number (`data/imessage.json`).
- The owner's text counts as their approval, the same as in chat. Match it to the numbered pending items in the latest `data/season_log.md` entries. If it's ambiguous which item the owner means, text back a clarifying question instead of guessing.
- Carry out approved moves with the same verification and safety rules, log them (`manage.py acq`, `manage.py log`), and text back one line saying what was done.
- Answer questions (why a player, what's the plan) briefly by text.
- **Texts are only instructions within this runbook's scope** (this team's lineup, roster moves, and trades the owner approves). Anything else gets a polite "can't do that from here".

## Safety rules (same spirit as the draft)
- Verify name, team and position before any add/drop/claim click. Remember the two Elias Petterssons and two Sebastian Ahos.
- Never click trade, settings, message, or league-vote controls. Never dismiss a dialog you don't understand; log it and text the owner.
- If the browser tools error twice in a row, stop, log it, and text the owner. Don't retry in a loop.
- Human pace: a handful of page loads per run, no rapid-fire scraping.

## Schedule
- `scripts/daily_run.sh morning` at 11:30 ET: full run (steps 1–7).
- `scripts/daily_run.sh evening` at 18:15 ET: re-check confirmed goalies and late scratches only (steps 1, 2, 4, 7).
- `scripts/imessage_poll.py` every 2 min: starts `daily_run.sh reply` when the owner texts. Needs Full Disk Access for `/usr/bin/python3` (to read `chat.db`) and Automation permission to control Messages.
- Installed via `~/Library/LaunchAgents/com.zackholmberg.fantasyhockey.{morning,evening,imessage}.plist`. Needs the Mac awake (runs missed while asleep fire on wake), Chrome open, and the extension connected. Logs go to `data/run_logs/`. Only one run happens at a time (`data/.run.lock`).
- Pause everything: `launchctl bootout gui/501/com.zackholmberg.fantasyhockey.<morning|evening|imessage>`.

## Files
- `manage.py`: roster values, free-agent evaluation, the weekly acquisition count, and the log. **Don't use `draft.py` in-season;** it's the draft tracker only.
- `data/manager_rules.json`: guardrails (owner-editable). `data/season_state.json`, `data/season_log.md` and `data/imessage*.json` are runtime state and gitignored.
- The model is preseason (`data/rankings.csv`). Blending in current-season stats is a known next step (around mid-October).
