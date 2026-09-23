# Yahoo Fantasy API: status and gotchas (researched 2026-09-23)

## Status: blocked until Yahoo approves the app
- Since **2026-07-22**, every Fantasy endpoint returns `403 {"error":{"description":"This application is not authorized to perform this action."}}` for any app Yahoo hasn't manually approved. That includes old apps that used to work and new apps. OAuth (authorize, token, refresh) still returns 200. That matches exactly what we saw.
- The old docs now redirect to a new approval portal, https://sports.yahoo.com/developer/. The app-creation form no longer offers a Fantasy Sports permission at all.
- **Things that do NOT fix it:** scope values (`fspt-r`/`fspt-w`), Confidential vs Public client, redirect URI, OpenID permissions, re-authorizing, or creating a new app. We tried the first few and they failed as predicted.
- **The only reported fix: apply at https://sports.yahoo.com/developer/access/.**
  - Say it's personal, single-league, read-only use.
  - Expected users: Small (<1,000).
  - Include the existing Client ID.
  - Fill every field in detail; incomplete submissions are "closed without further correspondence."
- There's no published turnaround, and as of 2026-09-23 no public report of anyone being approved. Plan on no API for the draft.
- Sources:
  - https://github.com/uberfastman/yfpy/issues/84 (opened 2026-07-22)
  - https://github.com/PipedreamHQ/pipedream/issues/21907 (2026-09-05)
  - https://github.com/krger/yahoo-fantasy-mcp
  - https://sports.yahoo.com/developer/access/
- Background: Yahoo quietly removed write access for new apps around 2025-10 (yfpy #79).

## Gotchas once access is approved
- **Redirect URI:** `oob` is rejected. `https://localhost:8080` worked for our token exchange. yahoo_oauth defaults `callback_uri` to `oob` and also sends it on **refresh**, so `oauth2.json` must include `"callback_uri": "https://localhost:8080"`. It already does.
- **League key:** use the numeric form, `<game_key>.l.23491`. `yahoo_sync.connect()` resolves `game_id()` for `nhl` first. If the league was renewed, confirm the ID in the Yahoo URL.
- **Draft results:** `League.draft_results()` silently drops empty (pre-draft) slots. `yahoo_sync.draft_slots()` parses the raw response for exactly this reason, so it can report the draft slot. It's supposed to update live during the draft; latency isn't documented.
- **Rate limits:** the numbers aren't published and limits are per app. When throttled, Yahoo returns a non-JSON "Request denied"/999 body and blocks the app for a while. Polling every 10–15 s (240–360 requests/hour) is anecdotally fine. Back off on any non-200 or non-JSON response. `free_agents()`/`taken_players()` page 25 at a time, so run `eligibility` once and cache it.
- **Tokens:** they expire after 1 hour. yahoo_oauth only checks and refreshes in `OAuth2.__init__`, and rewrites the file when it does. `yahoo_sync.py` builds a new `OAuth2` on every run, so one-shot calls are fine. A long-running poller must re-create it or refresh before 59 minutes. The library's own retry-on-expiry refreshes in memory only.
- **Errors:** `Yhandler.get` raises `RuntimeError(bytes)` on any non-200. Decode the bytes before matching on message text.
- **JSON shape:** collections are dicts keyed `"0"`, `"1"`, … plus `"count"`, and entities are lists of single-key dicts. Use objectpath `$..` queries or a flattening helper.
- **Terms:** approved apps must show the attribution "Fantasy data provided by Yahoo Fantasy." Scraping or automating Yahoo pages may violate the Fantasy API terms.

## Related project
https://github.com/spilchen/yahoo_fantasy_mcp is an MCP server from the author of yahoo_fantasy_api. It offers 27 read-only tools (rosters, free agents, waivers, matchups, and so on) but **no draft tools**, and uses the same auth. That means the same 403 until the app is approved. It could be worth adding for in-season management once access is approved; it reads our `oauth2.json` format.
