# yahoo-fantasy-hockey

Draft prep and live draft co-pilot for Yahoo league 23491 (2026-27). The context for Claude is in `CLAUDE.md`.

## New machine: set up for the draft (about 2 minutes)

```sh
gh repo clone ZackHolmberg/yahoo-fantasy-hockey && cd yahoo-fantasy-hockey
git config user.name "Zack Holmberg" && git config user.email "zack_holmberg@outlook.com"
python3 draft.py reset && python3 draft.py best 5     # smoke test; needs only python3
claude
```

Then start the session with:

> Read CLAUDE.md. We're drafting now. My draft slot is __ and my team name is __. I'll paste Yahoo's draft results before each of my picks; give me one pick and a backup, fast.

## Optional: full environment (only for refreshing stats or Yahoo OAuth)

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python fetch_stats.py          # refresh data/raw from the NHL stats API
python3 project.py > data/rankings_top200.txt && python3 cheatsheet.py
```

Yahoo OAuth (currently blocked by a 403; see CLAUDE.md): create a gitignored `oauth2.json` with
`{"consumer_key": "...", "consumer_secret": "...", "callback_uri": "https://localhost:8080"}`, then run
`.venv/bin/python auth.py url` and `.venv/bin/python auth.py <code>`.
