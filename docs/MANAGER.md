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
The scripts do the reading and the math; you act on their report. Don't re-derive what the report already decided.
1. **Read:** open a new tab on `https://hockey.fantasysports.yahoo.com/hockey/23491/11`. If Yahoo shows a login page, stop and text the owner. Never enter credentials. Read `scripts/yahoo_read.js` and run its contents with the javascript tool. If it answers "N chunks", call `window.__fhChunk(0)` ... `window.__fhChunk(N-1)`.
2. **Report:** `python3 manage.py report '<chunk0>' '<chunk1>' ...`, passing every chunk verbatim and in order. It syncs the roster and prints:
   - **ACTIONS:** lineup moves for today (only moves that change who plays), IR moves, `AUTO-OK` add/drops.
   - **ASK OWNER**, **FYI**, and a **TEXT DRAFT**.
3. **Act:** do each ACTION on the Yahoo pages. Verify name, team and position on the row before clicking. For an `AUTO-OK` add/drop, run the `manage.py acq ... --auto` command the report prints, right after the move goes through.
   - **Goalie:** the report starts the best goalie with a game. Check Yahoo's "Starting" tag (or DailyFaceoff). If he isn't the confirmed starter, use the alternative the FYI names.
4. **Verify:** repeat steps 1-2. ACTIONS should now be empty. If something won't go away (a locked player, a full IR), log why. Don't loop.
5. **Trades** (Monday only): look for other teams' surplus where we're thin. Draft a proposal only when the model shows value for both sides. **Never send it:** list it for the owner.
6. **Report:** `python3 manage.py log "..."` (what you did, plus ASK items numbered as the report says). Then send the TEXT DRAFT with `scripts/imessage_send.sh "..."`, edited to match what actually happened. If the draft says none, don't text.
   - The model is preseason. After ~15 games, mention it when a player's current-season FP/G on Yahoo and the model disagree by a lot.

## Owner replies (iMessage)
`scripts/imessage_poll.py` (launchd, every 2 min) starts a `reply` run when the owner texts from their own number (`data/imessage.json`).
- The owner's text counts as their approval, the same as in chat. Match it to the numbered pending items in the latest `data/season_log.md` entries. If it's ambiguous which item the owner means, text back a clarifying question instead of guessing.
- Carry out approved moves with the same verification and safety rules, log them (`manage.py acq`, `manage.py log`), and text back one line saying what was done.
- Answer questions (why a player, what's the plan) briefly by text.
- **Texts are only instructions within this runbook's scope** (this team's lineup, roster moves, and trades the owner approves). Anything else gets a polite "can't do that from here".

## Team names
Refer to other league teams **only by alias**: `T<n>`, where n is the Yahoo team number in the team's URL (`/hockey/23491/<n>`). Use the alias in everything you write: notes, `manage.py log`, texts, and your final summary. Never copy a team's display name out of the page. Some names trip content filters and stall the run. `team_alias.py` scrubs known names from logs and texts as a backstop (map in `data/team_aliases.json`, gitignored).

## Safety rules (same spirit as the draft)
- Verify name, team and position before any add/drop/claim click. Remember the two Elias Petterssons and two Sebastian Ahos.
- Never click trade, settings, message, or league-vote controls. Never dismiss a dialog you don't understand; log it and text the owner.
- If the browser tools error twice in a row, stop, log it, and text the owner. Don't retry in a loop.
- Human pace: a handful of page loads per run, no rapid-fire scraping.

## Scheduled runs are scripts, not Claude (since 2026-10-04)
launchd runs `scripts/daily_auto.py`, which needs no Claude call on most days:
- **Yahoo:** `yahoo_bot.py apply` reads the site with Playwright in a dedicated browser profile (`data/yahoo_profile/`, gitignored), which the owner signed into once with `.venv/bin/python yahoo_bot.py login`. It sets the lineup/IR in Yahoo's edit-roster form and makes `AUTO-OK` add/drops, checking player names on the page before each submit. Then it re-checks. If Yahoo signs the bot out, the run texts the owner and falls back to the Claude run (`daily_run.sh morning|evening`).
- **ESPN:** `report --fetch` (API with the owner's cookies), then `espn_bot.py apply` makes the ACTIONS through ESPN's write API. Lineup moves use the current scoring period, adds/drops the transaction period. A locked lineup (`... is locked`) is reported and retried next run. No LLM or browser involved.
- **Texts:** `llm.py` phrases them, with a plain template as fallback. The script logs to the season log and numbers questions Q../E...
- **Replies:** `imessage_poll.py` hands the owner's texts to `scripts/reply_auto.py`. The LLM layer reads the free-form text into one intent (approve/reject an open question, trade check, trade ideas, question). The script validates it, acts (`yahoo_bot.py`/`espn_bot.py swap`, `manage.py trade`/`trade-ideas`), and the LLM phrases the answer. Trades are never sent: the owner gets the numbers and a note to paste. Test without side effects: `REPLY_DRY=1 scripts/reply_auto.py "text"`.
- **LLM driver:** `data/llm.json` `"driver": "local"` (Qwen on this Mac) or `"claude"` (claude CLI, no tools). Nothing else changes when you switch.
- **Goalies:** the Yahoo plan uses DailyFaceoff's starting-goalie statuses (confirmed > likely > unconfirmed). The 18:15 run catches late confirmations.
- **Mondays:** both leagues' texts include up to two 1-for-1 trade ideas that improve both sides' best lineup (`manage.py trade-ideas`).
- Logs: `data/run_logs/<date>_auto_<league>.log`. The Claude runbook sections above still apply whenever Claude is the one running.

## Schedule
- `scripts/daily_auto.py yahoo morning` at 11:30 ET (falls back to `daily_run.sh morning`).
- `scripts/daily_auto.py yahoo evening` at 18:15 ET (falls back to `daily_run.sh evening`).
- `scripts/imessage_poll.py` every 2 min: starts `daily_run.sh reply` when the owner texts. Needs Full Disk Access for `/usr/bin/python3` (to read `chat.db`) and Automation permission to control Messages.
- Installed via `~/Library/LaunchAgents/com.zackholmberg.fantasyhockey.{morning,evening,imessage}.plist`. Needs the Mac awake (runs missed while asleep fire on wake), Chrome open, and the extension connected. Logs go to `data/run_logs/`. Only one run happens at a time (`data/.run.lock`).
- Pause everything: `launchctl bootout gui/501/com.zackholmberg.fantasyhockey.<morning|evening|imessage>`.

## Files
- `manage.py`: roster values, free-agent evaluation, the weekly acquisition count, and the log. **Don't use `draft.py` in-season;** it's the draft tracker only.
- `data/manager_rules.json`: guardrails (owner-editable). `data/season_state.json`, `data/season_log.md` and `data/imessage*.json` are runtime state and gitignored.
- The model is preseason (`data/rankings.csv`). Blending in current-season stats is a known next step (around mid-October).
