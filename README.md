# yahoo-fantasy-hockey

Draft prep and in-season tooling for a Yahoo Fantasy Hockey league.

## Setup

```sh
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements.txt
```

Create `oauth2.json` (gitignored) with your Yahoo app credentials:

```json
{
  "consumer_key": "...",
  "consumer_secret": "...",
  "callback_uri": "https://localhost:8080"
}
```

Authorize once:

```sh
.venv/bin/python auth.py url      # open the printed URL, approve access
.venv/bin/python auth.py <code>   # paste the code= value from the redirect URL
```
