# Expert-board API mock rehearsal — October 17, 2026

Completed practice league **2035580386**, team 18, from slot 15 in a 16-team, 12-round snake draft. ESPN recorded all **192** selections and all **12** team picks. The real league (2141453434) was not drafted or modified.

The first pick was made through the visible browser before the user requested API-only selection. Every subsequent pick was submitted and acknowledged through the native draft API: **11 API-confirmed picks, one browser-confirmed pick, zero ESPN autopicks**, with no unconfirmed write remaining.

## Selection policy

Used the checked 2026–27 RotoWire points board, best legal available, with current profile/roster/injury verification and persistent player/team bans. The experimental timing hybrid and historical projection/VOR ordering were not used. All 12 selections have a published RotoWire rank; none required the ESPN-completed tail. Every API receipt contains allowed current availability evidence. No injury review was automatically accepted.

## Final roster

| Overall pick | Player | Eligible positions | Published RotoWire rank | ESPN STANDARD rank | Confirmation |
|---:|---|---|---:|---:|---|
| 15 | Tyrese Maxey | PG, SG | 9 | 13 | Browser before switch |
| 18 | Karl-Anthony Towns | C | 13 | 24 | API receipt |
| 47 | Walker Kessler | C | 37 | 69 | API receipt |
| 50 | Brandon Miller | SG, SF | 42 | 60 | API receipt |
| 79 | Jaren Jackson Jr. | PF, C | 54 | 84 | API receipt |
| 82 | Dylan Harper | PG, SG | 73 | 85 | API receipt |
| 111 | Zach Edey | C | 80 | 118 | API receipt |
| 114 | Paul George | SF, PF | 90 | 109 | API receipt |
| 143 | Yaxel Lendeborg | SF, PF | 111 | 173 | API receipt |
| 146 | Ajay Mitchell | PG, SG | 113 | 226 | API receipt |
| 175 | Christian Braun | SG, SF | 140 | 208 | API receipt |
| 178 | Tari Eason | SF, PF | 148 | 205 | API receipt |

## Verification and visible-browser behavior

The completed draft has 192 unique player selections. All 12 roster entries match authoritative server picks. Eleven durable API receipts match their exact team, player and pick number. The write journal is empty. Independent final roster checks passed the four-primary-center cap and found a legal assignment for all nine starting slots.

The fresh mock ran with a 60-second clock without pausing. Autopick was visibly confirmed off before the API hand-off. ESPN allows one active draft connection for this team: when the API joined, the authenticated ESPN viewing tab received a Duplicate Connection message. Reconnecting that tab would displace the API. A visible, read-only local browser viewer displayed the live API picks using local receipts, without opening another ESPN connection. The first setup attempt (practice 175906646) timed out during live-state tracking work and completed on ESPN autopick; it was discarded and is not included in these results.

The local viewer is `http://127.0.0.1:8768/`, served by the ignored rehearsal viewer helper while it remains running. The completed snapshot and evidence are retained under `basketball/data/headed-practice-20261017/runtime/`: `draft-result.json`, `draft-receipts.json`, `api-watch.log`, `expert-rehearsal-summary.json` and `api-mock-complete.png`. Runtime credentials and raw private data remain ignored.

This verifies expert-order execution, availability gates and roster legality in practice. It is not an evaluation of future player performance. The real draft connection still needs verification when its room opens.

Source: [RotoWire current points rankings, NBA.com syndication](https://www.nba.com/news/nba-fantasy-top-150-for-2026-27-points-leagues).
