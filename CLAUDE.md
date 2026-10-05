# Yahoo fantasy hockey: draft co-pilot and in-season manager

You (Claude) are helping the owner draft and manage a team in **Yahoo league 23491**. Full settings are in `docs/LEAGUE.md`. Read it first. It's H2H points, one G slot, and hits/blocks/faceoffs/saves score heavily.

## In-season (current phase)
The draft is done (Sep 23, 2026). The owner's team is **Suzuki For Hart** (drafted 8th). The season starts Tue Sep 29. Claude manages the team daily per **`docs/MANAGER.md`**: headless runs at 11:30 and 18:15 ET via launchd, and the owner talks to Claude by iMessage. That runbook's authority table decides what Claude may do alone (lineups, IR moves, `AUTO-OK` add/drops) and what needs the owner (trades, goalie swaps, anything else). If the owner says "manage the team" in a session, follow the same runbook.

**Second league (ESPN 1034056432, "Leafs suck", 6 teams, drafted Sep 30, 2026):** same team name, managed per **`docs/MANAGER_ESPN.md`** (weekly lineup lock, its own scoring and rankings in `espn/data/`; use `python3 manage.py --league espn ...`). Daily headless run at 10:30 ET plus Sunday 21:00.

**Since 2026-10-04 the daily work runs as scripts** (`scripts/daily_auto.py`, `yahoo_bot.py`, `espn_bot.py`, `scripts/reply_auto.py`) with a switchable LLM layer (`llm.py`, driver in `data/llm.json`). See the "Scheduled runs are scripts" section of `docs/MANAGER.md`.

The draft sections below are kept for next season.

## Division of labor during the draft
**Plan A: browser-driven.** You read the Yahoo draft room and make the owner's picks through the Claude in Chrome extension, with the owner watching and able to override. **Plan B: paste.** If the browser tools aren't connected or misbehave, the owner clicks and pastes Draft Results; you recommend one pick plus one backup, fast. The owner has 75 seconds per pick either way.

## Plan A: browser-driven draft
Setup on this machine (the owner does it before the draft):
1. Install the Claude in Chrome extension in Chrome, then run `/chrome` in Claude Code to connect. Browser tools are Chrome only; there's no Firefox extension.
2. Invoke the `claude-in-chrome` skill before using any browser tool.
3. The owner opens the Yahoo draft room (league 23491 → Draft) in Chrome and leaves that tab alone.
4. **Rehearse** in a Yahoo mock draft lobby first, if time allows (Yahoo Fantasy Hockey → Mock Draft). Do 2–3 picks end to end: read the board, sync the tracker, search for the player, click Draft, confirm. Learn the page layout there, not in the real draft.
5. Belt and braces: have the owner put ~15 top targets in the Yahoo **draft queue** before the draft. If a pick times out, Yahoo autopicks from the queue, not from its default rankings.

Loop for every pick:
1. **Sync:** read the draft room's Draft Results or pick list (page text), save it to a temp file, and run `python3 draft.py paste < file`. Record the owner's own picks with `python3 draft.py mine "Name"`. Identify them from the owner's team name in the draft room.
2. **Decide** from `python3 draft.py best 20` plus the "How to pick" rules. Do it while other teams are picking, so the choice is ready before the owner's turn starts.
3. **Execute** when it's the owner's turn: use the draft room's player search, type the player's name, and **verify the exact name, team and position in the result row** before clicking Draft. If the top choice was just taken, use the prepared backup.
4. **Confirm:** re-read the page, check the pick registered to the owner's team, run `draft.py mine`, and tell the owner in one line ("Took X (pos, team). Next pick #N.").

Safety rules (non-negotiable):
- Never click Draft on a row you haven't verified by name. Two Elias Petterssons and two Sebastian Ahos exist; check position and team.
- **Time budget:** if the pick isn't clicked with ~25 s left on Yahoo's clock, stop, tell the owner "pick X now" and let them click. A late human pick beats a wrong or autopicked one.
- Don't click anything else in the draft room: no trades, no settings, no leaving the room. Never dismiss dialogs you don't understand; ask the owner.
- If the page layout confuses you, or the browser tools error twice in a row, switch to Plan B immediately.
- Caveat for the owner: automating Yahoo pages may conflict with Yahoo's terms of use. The owner has chosen to accept that; keep the automation to their own picks at human pace.

## Plan B: paste Draft Results
The Yahoo API is **blocked for unapproved apps** (every Fantasy endpoint returns 403 since 2026-07-22; see `docs/yahoo_api_notes.md`). Creating a new app does not help; only Yahoo's manual approval does. So draft tracking comes from the browser (Plan A) or owner pastes (Plan B).

Still, if the owner has a venv and `oauth2.json` on this machine, spend **30 seconds** on `.venv/bin/python yahoo_sync.py check` at the start. If it prints `OK: API access works` (the approval came through), use the API path instead:

```sh
.venv/bin/python yahoo_sync.py eligibility   # once: caches Yahoo C/LW/RW eligibility
.venv/bin/python yahoo_sync.py sync          # each turn: rebuilds state from Yahoo, shows slot, "MY TURN NOW", best available
```

`sync` is idempotent and knows the owner's team from the login. It was only tested against a mock, so on any unexpected error, drop back to paste immediately and don't debug during the draft. Don't poll faster than every ~10–15 s (Yahoo throttles per app).

## Paste workflow (used by both plans for tracker sync)
All commands run from the repo root with plain `python3`, no venv needed.

```sh
python3 draft.py reset                       # once, before the draft
pbpaste | python3 draft.py paste             # owner copied Yahoo's Draft Results: mark all as taken
python3 draft.py taken "Name" "Name" ...     # or record others' picks by name (fuzzy match)
python3 draft.py mine "Name"                 # record the owner's pick
python3 draft.py undo "Name"                 # fix a mistake
python3 draft.py best 20                     # best available by VOR + unfilled starters
```

- If the owner pastes Draft Results text into chat instead of the clipboard, write it to a temp file and pipe it: `python3 draft.py paste < file`.
- **Always confirm which pasted picks are the owner's** and record those with `mine`. Ask for the owner's team name/draft slot at the start. The slot was TBD when this was written.
- `paste` only knows players in `data/rankings.csv`. Rookies and players with no NHL history (McKenna, Martone, Frondell, Kantserov, Stenberg, I. Protas, Carter Hart) are ignored, so track them mentally.
- Name collision: there are two **Elias Petterssons** (VAN C, and VAN D ranked ~470). `paste` marks both if the name appears. Harmless unless the owner wants the D.

## How to pick
1. Start from `draft.py best`, which sorts by VOR (value over replacement at the position). The 2nd and 3rd goalies are already discounted (x0.5, x0.2), because only one G starts per day.
2. **Market timing (judgment, not backtested):** when the top candidates are within ~15 VOR, take the one the market will grab sooner (see ADP in `docs/research_2026-09-23.md`). Players we rank far above ADP (Seider, Weegar, Sherwood, Cuylle, Greaves, Hofer, Dobes) can often wait a round.
3. **Yahoo dual eligibility:** the model uses NHL primary positions. If Yahoo lists a C as also LW/RW, he's worth more, because wings run thin (replacement ~305 FP for wingers vs ~425 for centers). After `yahoo_sync.py eligibility` runs, `best` shows `Yahoo:C/RW` and counts every eligible position toward `<- NEED`. Without it, ask the owner when it matters.
4. Fill the starters by the end: 2C, 2LW, 2RW, 4D, 1G, plus a 2nd G by the mid rounds and a 3rd late. Bench is 5 (16-man roster). The tracker flags `<- NEED`.
5. Watch the notes column for injury and role flags. Avoid Hellebuyck (suspended, trade request) and unsettled goalie situations (EDM, NJD, PIT, WPG).
6. Rookies: only in the late rounds, unless you have a specific reason.

## Files
| Path | What |
|---|---|
| `docs/LEAGUE.md`, `docs/league_settings.png` | League settings and what they imply |
| `docs/research_2026-09-23.md` | Offseason moves, injuries, goalie depth charts, rookies, ADP |
| `data/rankings.csv` | **The rankings the tracker uses** (projected FP, VOR, notes) |
| `DRAFT_SHEET.md` | Printable round-by-round backup sheet |
| `data/adjustments.json` | Manual overrides from research (team, proj_gp, fpg_mult, note, remove) |
| `project.py` | Builds rankings from `data/raw/` + adjustments (stdlib) |
| `cheatsheet.py` | Rebuilds DRAFT_SHEET.md from rankings.csv |
| `draft.py` | Live tracker (stdlib) |
| `yahoo_sync.py` | Yahoo API check / draft sync / eligibility (blocked until Yahoo approves the app) |
| `docs/yahoo_api_notes.md` | Why the API is blocked, how to get approved, gotchas after approval |
| `backtest.py`, `data/backtest_results.txt` | Draft simulation on 2024-25 and 2025-26 |
| `fetch_stats.py` | Pulls NHL stats API data into `data/raw/` (needs `requests`) |
| `auth.py` | Yahoo OAuth, two steps (`url` [noscope], then `<code>`) |
| `docs/MANAGER.md` | In-season runbook: authority, daily steps, iMessage replies, schedule |
| `manage.py`, `data/manager_rules.json` | In-season roster values, free-agent evaluation, acquisition guardrails |
| `scripts/daily_run.sh`, `scripts/imessage_*.{sh,py}` | Headless run entry point; iMessage send/poll |

To apply late news, edit `data/adjustments.json`, then run `python3 project.py > data/rankings_top200.txt && python3 cheatsheet.py`. That's safe mid-draft: `draft_state.json` stores names, not ranks.

## Model summary
- Projected FP/G = 65/35 blend of the 2025-26 and 2024-25 seasons, scored with the league's exact point values. Games played lean 80/20 on the most recent season, capped at 80 for skaters and 62 starts for goalies. Players under 60 career GP are regressed.
- Replacement ranks: C/LW/RW 30, D 56, G 26.
- **Backtest** (bots in a 12-team snake draft, scored on actual season totals): won the league 60–76% of simulations vs an 8% baseline, top 3 in 85–99%, from every draft slot. Caveats: the opponents are bots, not humans; it measures season totals, not H2H weekly matchups; and it has no dual eligibility. The real edge is smaller but real: most managers underweight hits, blocks, faceoffs and saves.

## Yahoo API status
Blocked pending Yahoo approval. Full details and the post-approval gotchas are in `docs/yahoo_api_notes.md`.
- OAuth works (`auth.py`), but every Fantasy endpoint returns 403 "This application is not authorized to perform this action". That happens to every unapproved app since 2026-07-22, including new apps and whatever scope is requested.
- Fix: the owner applies at https://sports.yahoo.com/developer/access/ (personal, single-league, read-only, Small; include the Client ID). There's no published turnaround.
- The old app ID `yCxtir99` is the one to get approved. Its secret was pasted in a chat transcript; regenerate it if the console allows.
- Once approved: set up the venv (`uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt`). The owner creates the gitignored `oauth2.json` (`consumer_key`, `consumer_secret`, `"callback_uri": "https://localhost:8080"`). Then run `auth.py url`, then `auth.py <code>`, then `yahoo_sync.py check`.
- In-season, consider https://github.com/spilchen/yahoo_fantasy_mcp (read-only MCP tools for rosters, free agents and waivers; same auth; no draft tools).

## Repo conventions
- Private repo `github.com/ZackHolmberg/yahoo-fantasy-hockey`. This is the owner's **personal** GitHub. Commit as `Zack Holmberg <zack_holmberg@outlook.com>`, set per-repo (`git config user.email`), never a work identity.
- Never commit `oauth2.json` or tokens (gitignored).
