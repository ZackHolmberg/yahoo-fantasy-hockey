# yahoo-fantasy-hockey

Draft prep and live draft co-pilot for Yahoo league 23491 (2026-27). The full context for Claude is in `CLAUDE.md`.

## ESPN fantasy basketball

The basketball assistant is configured for **league 2141453434, team 18, season 2027** using settings verified on ESPN on October 16, 2026. It supports points/category/roto analysis, draft tracking and ADP timing, auction budgets, daily/weekly lineups, streaming, IR, acquisitions/waivers, trade evaluation, and portable scheduled runs. Changes to ESPN require an explicit `--execute` flag.

```sh
python -m pip install -r requirements-basketball.txt
python -m playwright install chromium
python -m basketball login
python -m basketball fetch
python -m basketball draft best
python -m basketball report
```

See [the basketball guide](docs/BASKETBALL.md) for all commands, browser export, draft-room configuration, and live-verification limits. Hockey commands and state remain independent.

## New machine setup (about 2 minutes)

```sh
gh repo clone ZackHolmberg/yahoo-fantasy-hockey && cd yahoo-fantasy-hockey
git config user.name "Zack Holmberg" && git config user.email "zack_holmberg@outlook.com"
python3 draft.py reset && python3 draft.py best 5     # smoke test; needs only python3
```

### Draft night, Plan A: Claude drives the draft room in Chrome
1. Install the **Claude in Chrome** extension in Chrome (Chrome only; no Firefox extension), start `claude` in this repo, and run `/chrome` to connect.
2. Open the Yahoo draft room for league 23491 in Chrome.
3. If time allows, rehearse a few picks in a Yahoo **mock draft** first.
4. Put ~15 top targets in your Yahoo draft queue, so a timed-out pick autopicks sensibly.
5. Watch every pick. Claude hands a pick back to you if it's running out of time (about 25 seconds left).

### Draft night, Plan B: paste Draft Results (no setup needed)
Copy Yahoo's Draft Results list and paste it to Claude before each of your picks. It runs `python3 draft.py paste` and replies with a pick and a backup.

### Yahoo API: blocked until Yahoo approves the app
Since 2026-07-22, Yahoo returns 403 on every Fantasy endpoint for unapproved apps. **Creating a new app doesn't help.**
Apply at https://sports.yahoo.com/developer/access/ (personal, single-league, read-only; include the Client ID).
After approval, follow "Yahoo API status" in `CLAUDE.md`. Details are in `docs/yahoo_api_notes.md`.

## Start the Claude session

```sh
claude
```

> Read CLAUDE.md. We're drafting now with Plan A (browser). My team name is __ and my draft slot is __. The draft room is open in Chrome. Rehearse in the mock draft tab first if it's open.

## Refreshing data (optional)

```sh
.venv/bin/python fetch_stats.py                                        # re-pull NHL stats
python3 project.py > data/rankings_top200.txt && python3 cheatsheet.py  # rebuild rankings + DRAFT_SHEET.md
```
