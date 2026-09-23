# Yahoo fantasy hockey: draft co-pilot

You (Claude) are helping the owner draft and manage a team in **Yahoo league 23491**. The live draft is **Wed Sep 23, 2026, 6:00pm EDT**, with **75 seconds per pick**, 12 teams, snake order. Full settings are in `docs/LEAGUE.md`. Read it first. It's H2H points, one G slot, and hits/blocks/faceoffs/saves score heavily.

## Division of labor during the draft
There is no browser automation: the owner clicks picks in Yahoo, and you track the draft and recommend. Keep replies **short and fast**: one pick plus one backup and a few words of reasoning. The owner has 75 seconds.

## Preferred path: Yahoo API sync
The owner plans to set up a **fresh Yahoo app** on the draft machine before the draft (the first app got a 403 on every Fantasy endpoint; see "Yahoo API setup" below). If `yahoo_sync.py check` succeeds, use the API path. The owner doesn't need to relay picks at all.

```sh
.venv/bin/python yahoo_sync.py check         # first: confirms auth, league settings, owner's team
.venv/bin/python yahoo_sync.py eligibility   # once before the draft: caches Yahoo C/LW/RW eligibility
.venv/bin/python yahoo_sync.py sync          # each turn: rebuilds state from Yahoo, shows slot, "MY TURN NOW", best available
```

- `sync` is idempotent (it rebuilds `data/draft_state.json` from Yahoo), so run it whenever the owner says "my turn", or before every recommendation.
- It knows the owner's team from the logged-in account, so there's no need to ask which picks are theirs. It also reports the draft slot once Yahoo sets the order.
- Optional: poll `sync` every ~10–15 s in the background (e.g. with the Monitor tool) and alert the owner when it prints `MY TURN NOW` or they're 2 picks away.
- Drafted players missing from our rankings (rookies) are listed as "not in rankings" but still count toward pick numbers.
- The sync success path was only tested against a mock (the real API was 403 at the time). If it throws anything other than the 403 message, don't debug during the draft: switch to the fallback immediately.

## Fallback: paste Draft Results
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
4. Fill the starters by the end: 2C, 2LW, 2RW, 4D, 1G, plus a 2nd G by the mid rounds and a 3rd late. Bench is 6. The tracker flags `<- NEED`.
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
| `yahoo_sync.py` | **Preferred:** Yahoo API check / draft sync / eligibility (needs venv + oauth2.json) |
| `backtest.py`, `data/backtest_results.txt` | Draft simulation on 2024-25 and 2025-26 |
| `fetch_stats.py` | Pulls NHL stats API data into `data/raw/` (needs `requests`) |
| `auth.py` | Yahoo OAuth, two steps (`url` [noscope], then `<code>`) |

To apply late news, edit `data/adjustments.json`, then run `python3 project.py > data/rankings_top200.txt && python3 cheatsheet.py`. That's safe mid-draft: `draft_state.json` stores names, not ranks.

## Model summary
- Projected FP/G = 65/35 blend of the 2025-26 and 2024-25 seasons, scored with the league's exact point values. Games played lean 80/20 on the most recent season, capped at 80 for skaters and 62 starts for goalies. Players under 60 career GP are regressed.
- Replacement ranks: C/LW/RW 30, D 56, G 26.
- **Backtest** (bots in a 12-team snake draft, scored on actual season totals): won the league 60–76% of simulations vs an 8% baseline, top 3 in 85–99%, from every draft slot. Caveats: the opponents are bots, not humans; it measures season totals, not H2H weekly matchups; and it has no dual eligibility. The real edge is smaller but real: most managers underweight hits, blocks, faceoffs and saves.

## Yahoo API setup (do this on the draft machine before the draft)
History: on the first machine OAuth worked, but every Fantasy endpoint (even `game/nhl` and `users;use_login=1/games`) returned 403 "This application is not authorized to perform this action". That happened both without and with `scope=fspt-r`, even though "Fantasy Sports: Read" was checked on the app. The likely cause is an app whose permissions didn't take. The old app (ID `yCxtir99`) should be deleted; its secret was exposed in a chat transcript.

Steps:
1. https://developer.yahoo.com/apps/create/ → **Confidential Client**, Redirect URI **`https://localhost:8080`** (Yahoo rejects `oob`), API permissions: check **Fantasy Sports → Read** *during creation*. Leave OpenID unchecked.
2. `uv venv --python 3.12 .venv && uv pip install --python .venv/bin/python -r requirements.txt` (Python 3.14's venv/ensurepip was broken on the old machine; 3.12 works).
3. The owner creates the gitignored `oauth2.json` themselves (don't ask them to paste secrets into chat):
   `{"consumer_key": "...", "consumer_secret": "...", "callback_uri": "https://localhost:8080"}`
4. `.venv/bin/python auth.py url` → owner opens it, approves, and the browser lands on a dead `https://localhost:8080/?code=...` page (expected) → `.venv/bin/python auth.py <code>`. Codes expire in minutes.
5. `.venv/bin/python yahoo_sync.py check`. If it's still 403, retry step 4 with `auth.py url noscope`. If still 403, **stop and use the paste fallback**; don't burn pre-draft time.

Tokens refresh automatically via `yahoo_oauth`, which rewrites `oauth2.json`.

## Repo conventions
- Private repo `github.com/ZackHolmberg/yahoo-fantasy-hockey`. This is the owner's **personal** GitHub. Commit as `Zack Holmberg <zack_holmberg@outlook.com>`, set per-repo (`git config user.email`), never a work identity.
- Never commit `oauth2.json` or tokens (gitignored).
