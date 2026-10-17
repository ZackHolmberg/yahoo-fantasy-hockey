# ESPN basketball API rehearsal

Completed October 17, 2026 in ESPN practice league **817724050**, team 18: a 16-team snake draft from position 8 with 12 rounds and 192 total selections. The real league (2141453434) was not drafted or modified.

**Result:** 11 picks confirmed by the direct WebSocket API, one ESPN auto-pick, and a legal 12-player roster covering all nine starting slots. ESPN also confirmed the live queue update.

| Overall pick | Player | Eligible positions | Selection |
|---|---|---|---|
| 8 | Jayson Tatum | SF, PF | API confirmed |
| 25 | Alperen Sengun | C | API confirmed |
| 40 | Kon Knueppel | SG, SF | API confirmed |
| 57 | Tyler Herro | PG, SG | ESPN auto-pick |
| 72 | Joel Embiid | C | API confirmed |
| 89 | Jalen Green | SG, SF | API confirmed |
| 104 | RJ Barrett | SG, SF | API confirmed |
| 121 | Quentin Grimes | SG, SF | API confirmed |
| 136 | Sandro Mamukelashvili | PF, C | API confirmed |
| 153 | Jay Huff | C | API confirmed |
| 168 | Russell Westbrook | PG | API confirmed |
| 185 | Cam Spencer | PG, SG | API confirmed |

The first three API selections exercised the execution engine directly; the remaining eight used the actual `draft watch --execute` command. ESPN auto-selected Tyler Herro at pick 57 after a 30-second turn reached the minimum 25-second clock guard and the client stopped. The rest of the run used the real league’s 60-second timer. The guard was retained.

The rehearsal verified authentication, the complete 1,096-player pool, versioned binary INIT decoding, queue preservation across reconnects, live turn/clock events, server selection receipts, and completed draft state. The final server result contained all 192 selections. Names and eligibility were resolved against the captured ESPN player pool.

ESPN deleted the custom mock league immediately after completion (subsequent draftInit returned HTTP 404). The client now saves draft-result.json with names and projections directly from the active session before closing, so later review does not depend on the practice league remaining available.

Local validation: 67 basketball backend tests pass, including 23 draft API cases and a real local WebSocket round trip. Live testing covered snake picks and queues; auction bids, season roster transactions and trades remain locally tested. ESPN’s unofficial protocol may change.

The clock guard can stop unattended drafting when a safe window is missed; ESPN may then auto-pick. Keep manual access to the draft room available. Another connection from a phone or browser can displace the API session.
