# yahoo-fantasy-hockey

Draft prep and live draft co-pilot for Yahoo league 23491 (2026-27). The full context for Claude is in `CLAUDE.md`.

## New machine setup (about 2 minutes)

```sh
gh repo clone ZackHolmberg/yahoo-fantasy-hockey && cd yahoo-fantasy-hockey
git config user.name "Zack Holmberg" && git config user.email "zack_holmberg@outlook.com"
python3 draft.py reset && python3 draft.py best 5     # smoke test; needs only python3
```

### Draft night: paste Draft Results (no setup needed)
Copy Yahoo's Draft Results list and paste it to Claude before each of your picks. It runs `python3 draft.py paste` and replies with a pick and a backup.

### Yahoo API: blocked until Yahoo approves the app
Since 2026-07-22, Yahoo returns 403 on every Fantasy endpoint for unapproved apps. **Creating a new app doesn't help.**
Apply at https://sports.yahoo.com/developer/access/ (personal, single-league, read-only; include the Client ID).
After approval, follow "Yahoo API status" in `CLAUDE.md`. Details are in `docs/yahoo_api_notes.md`.

## Start the Claude session

```sh
claude
```

> Read CLAUDE.md. We're drafting now. My team name is __ and my draft slot is __. I'll paste Yahoo's Draft Results before each of my picks; give me one pick and a backup, fast.

## Refreshing data (optional)

```sh
.venv/bin/python fetch_stats.py                                        # re-pull NHL stats
python3 project.py > data/rankings_top200.txt && python3 cheatsheet.py  # rebuild rankings + DRAFT_SHEET.md
```
