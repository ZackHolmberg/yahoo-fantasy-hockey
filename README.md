# yahoo-fantasy-hockey

Draft prep and live draft co-pilot for Yahoo league 23491 (2026-27). The full context for Claude is in `CLAUDE.md`.

## New machine setup (do before the 6:00pm EDT draft)

```sh
gh repo clone ZackHolmberg/yahoo-fantasy-hockey && cd yahoo-fantasy-hockey
git config user.name "Zack Holmberg" && git config user.email "zack_holmberg@outlook.com"
uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt
```

### Preferred: Yahoo API (about 10 minutes)
1. Create a **new** app at https://developer.yahoo.com/apps/create/:
   - **Confidential Client**
   - Redirect URI `https://localhost:8080`
   - Check **Fantasy Sports → Read** while creating the app
2. Create `oauth2.json` in the repo root. It's gitignored, so never commit it or paste it into chat:
   ```json
   {"consumer_key": "YOUR_CLIENT_ID", "consumer_secret": "YOUR_CLIENT_SECRET", "callback_uri": "https://localhost:8080"}
   ```
3. Authorize:
   ```sh
   .venv/bin/python auth.py url        # open the URL and approve; the browser then shows a dead localhost page
   .venv/bin/python auth.py <code>     # the value after code= in that page's address bar
   ```
4. Verify, then cache Yahoo position eligibility:
   ```sh
   .venv/bin/python yahoo_sync.py check
   .venv/bin/python yahoo_sync.py eligibility
   ```
   If `check` returns a 403, redo step 3 with `auth.py url noscope`. If it still fails, use the fallback below.

### Fallback: paste Draft Results
No setup needed. Copy Yahoo's Draft Results list and paste it to Claude before each of your picks. It runs `python3 draft.py paste`.

## Start the Claude session

```sh
claude
```

> Read CLAUDE.md. We're drafting now. The Yahoo API check [passed / failed]. My team name is __. Before each of my picks, give me one pick and a backup, fast.

## Refreshing data (optional)

```sh
.venv/bin/python fetch_stats.py                                        # re-pull NHL stats
python3 project.py > data/rankings_top200.txt && python3 cheatsheet.py  # rebuild rankings + DRAFT_SHEET.md
```
