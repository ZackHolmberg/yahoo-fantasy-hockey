# Yahoo fantasy hockey: draft co-pilot

You (Claude) are helping the owner draft and manage a team in **Yahoo league 23491**. The live draft is **Wed Sep 23, 2026, 6:00pm EDT**, with **75 seconds per pick**, 12 teams, snake order. Full settings are in `docs/LEAGUE.md`. Read it first. It's H2H points, one G slot, and hits/blocks/faceoffs/saves score heavily.

## Division of labor during the draft
There is no browser automation: the owner clicks picks in Yahoo, and you record picks and recommend. Keep replies **short and fast**: one pick plus one backup and a few words of reasoning. The owner has 75 seconds.

## Live draft loop
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
3. **Yahoo dual eligibility:** the model uses NHL primary positions. If Yahoo lists a C as also LW/RW, he's worth more, because wings run thin (replacement ~305 FP for wingers vs ~425 for centers). Ask the owner when it matters.
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
| `backtest.py`, `data/backtest_results.txt` | Draft simulation on 2024-25 and 2025-26 |
| `fetch_stats.py` | Pulls NHL stats API data into `data/raw/` (needs `requests`) |
| `auth.py` | Yahoo OAuth (currently blocked; see below) |

To apply late news, edit `data/adjustments.json`, then run `python3 project.py > data/rankings_top200.txt && python3 cheatsheet.py`. That's safe mid-draft: `draft_state.json` stores names, not ranks.

## Model summary
- Projected FP/G = 65/35 blend of the 2025-26 and 2024-25 seasons, scored with the league's exact point values. Games played lean 80/20 on the most recent season, capped at 80 for skaters and 62 starts for goalies. Players under 60 career GP are regressed.
- Replacement ranks: C/LW/RW 30, D 56, G 26.
- **Backtest** (bots in a 12-team snake draft, scored on actual season totals): won the league 60–76% of simulations vs an 8% baseline, top 3 in 85–99%, from every draft slot. Caveats: the opponents are bots, not humans; it measures season totals, not H2H weekly matchups; and it has no dual eligibility. The real edge is smaller but real: most managers underweight hits, blocks, faceoffs and saves.

## Yahoo API status
OAuth works, but every Fantasy endpoint returns 403 "This application is not authorized", even with `scope=fspt-r` and Fantasy Sports Read enabled on the app. The next step is to create a **fresh** Yahoo app (Confidential client, redirect `https://localhost:8080`, Fantasy Sports Read checked at creation). Credentials go in a gitignored `oauth2.json`: `{"consumer_key","consumer_secret","callback_uri":"https://localhost:8080"}`. It's not needed for the draft.

## Repo conventions
- Private repo `github.com/ZackHolmberg/yahoo-fantasy-hockey`. This is the owner's **personal** GitHub. Commit as `Zack Holmberg <zack_holmberg@outlook.com>`, set per-repo (`git config user.email`), never a work identity.
- Never commit `oauth2.json` or tokens (gitignored).
