"""ESPN league 1034056432 changes through ESPN's (unofficial) write API, with the owner's cookies. Stdlib only.

    python3 espn_bot.py apply --dry-run   # print the exact requests the report's ACTIONS would send; sends nothing
    python3 espn_bot.py apply             # send them, then re-read and verify
    python3 espn_bot.py swap "Add" "Drop" [--dry-run]   # one add/drop the OWNER approved (reply pipeline)
    python3 espn_bot.py add "Name" ["Name" ...] [--dry-run]  # pure adds into OPEN roster spots (owner-approved)

Only three kinds of change can be built here: lineup slot moves, IR moves, and the report's AUTO-OK add/drops (a
FREEAGENT move, or a WAIVER claim if the player is on waivers). Before sending, every player is checked against a
fresh read of our roster (owned by us, in the slot we think, slot legal for his position). ESPN applies a POST
all-or-nothing and has no server-side dry run, so --dry-run is the only preview. Every request and response is
appended to data/run_logs/espn_writes.log (cookies are never logged). Prints a final RESULT_JSON line.

Write shape: public research (github.com/jwulff/fantasy-sports PR #92, github.com/ryanjadhav/espn-fantasy). Slot ids
are this league's (F 3, D 4, G 5, bench 7, IR 8), read from its own roster data.
"""
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent
AUTH = REPO / "espn/data/espn_auth.json"
WRITE_LOG = REPO / "data/run_logs/espn_writes.log"
SEASON, LEAGUE, TEAM = 2027, 1034056432, 5
READ = f"https://lm-api-reads.fantasy.espn.com/apis/v3/games/fhl/seasons/{SEASON}/segments/0/leagues/{LEAGUE}"
WRITE = f"https://lm-api-writes.fantasy.espn.com/apis/v3/games/fhl/seasons/{SEASON}/segments/0/leagues/{LEAGUE}/transactions/"
SLOT = {"F": 3, "D": 4, "G": 5, "BE": 7, "IR": 8}
POS_SLOTS = {1: {3}, 2: {3}, 3: {3}, 4: {4}, 5: {5}}  # defaultPositionId -> legal starting slots (plus bench/IR)


def auth():
    a = json.loads(AUTH.read_text())
    if not a.get("espn_s2"):
        sys.exit("espn_bot: no espn_s2 in espn/data/espn_auth.json")
    return a


def request(url, body=None, fantasy_filter=None):
    a = auth()
    headers = {"Cookie": f"espn_s2={a['espn_s2']}; SWID={a.get('SWID', '')}", "User-Agent": "Mozilla/5.0",
               "Accept": "application/json", "X-Fantasy-Source": "kona", "X-Fantasy-Platform": "espn-fantasy-web"}
    if fantasy_filter:
        headers["x-fantasy-filter"] = json.dumps(fantasy_filter)
    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.load(e)
        except Exception:
            return e.code, {"raw": e.read().decode(errors="replace")[:500]}


def read_state():
    """Our roster (name -> id, slot, position) plus free agents/waivers (name -> id, status) and the transaction period."""
    code, league = request(READ + "?view=mRoster&view=mStatus")
    if code != 200:
        sys.exit(f"espn_bot: roster read failed (HTTP {code}): {json.dumps(league)[:300]}")
    mine = next(t for t in league["teams"] if t["id"] == TEAM)
    roster = {}
    for e in mine["roster"]["entries"]:
        p = e["playerPoolEntry"]["player"]
        roster[p["fullName"]] = {"id": p["id"], "slot": e["lineupSlotId"], "pos": p["defaultPositionId"]}
    status = league.get("status", {})
    # lineup (ROSTER) moves must use the CURRENT scoring period; adds/drops/claims use the transaction period
    # (ESPN answers TRAN_INVALID_SCORINGPERIOD_NOT_CURRENT otherwise; seen 2026-10-04: current 6, transaction 7)
    period = {"roster": league.get("scoringPeriodId") or status.get("latestScoringPeriod"),
              "move": status.get("transactionScoringPeriod") or league.get("scoringPeriodId")}
    code, fa = request(READ + "?view=kona_player_info", fantasy_filter={"players": {
        "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "limit": 300,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}})
    pool = {x["player"]["fullName"]: {"id": x["player"]["id"], "status": x.get("status")} for x in fa.get("players", [])}
    return roster, pool, period, auth().get("SWID")


def report_plan():
    out = subprocess.run([sys.executable, str(REPO / "manage.py"), "--league", "espn", "report", "--fetch", "--json"],
                         capture_output=True, text=True, cwd=REPO)
    if "PLAN_JSON " not in out.stdout:
        sys.exit(f"espn_bot: report failed:\n{out.stdout}{out.stderr}")
    text, _, plan = out.stdout.partition("\nPLAN_JSON ")
    return text, json.loads(plan)


def norm(name):
    return name.replace("’", "'").strip()


def build(plan, roster, pool, period, member):
    """Turn the report's plan into checked request bodies. Returns (bodies, problems)."""
    bodies, problems = [], []
    by = {norm(n): v for n, v in roster.items()}
    envelope = {"isLeagueManager": False, "teamId": TEAM, "executionType": "EXECUTE", "memberId": member}
    items = []
    targets = {n: s for n, s in plan["lineup"].items()} | {n: "IR" for n in plan["ir"]}
    for name, want in targets.items():
        p = by.get(norm(name))
        if not p:
            problems.append(f"{name}: not on our ESPN roster"); continue
        to = SLOT.get(want)
        if to is None or (to not in (SLOT["BE"], SLOT["IR"]) and to not in POS_SLOTS.get(p["pos"], set())):
            problems.append(f"{name}: slot {want} not legal for him"); continue
        if p["slot"] == to:
            continue  # already there (ESPN rejects same-slot moves)
        items.append({"playerId": p["id"], "type": "LINEUP", "fromLineupSlotId": p["slot"], "toLineupSlotId": to,
                      "fromTeamId": TEAM, "toTeamId": TEAM, "_name": name})
    if items:
        bodies.append(envelope | {"type": "ROSTER", "scoringPeriodId": period["roster"], "items": items})
    for sw in plan["swaps"]:
        add, drop = pool.get(norm(sw["add"])) or pool.get(sw["add"]), by.get(norm(sw["drop"]))
        if not add:
            problems.append(f"add {sw['add']}: not a free agent or on waivers any more"); continue
        if not drop:
            problems.append(f"drop {sw['drop']}: not on our roster"); continue
        kind = "WAIVER" if add["status"] == "WAIVERS" else "FREEAGENT"
        bodies.append(envelope | {"type": kind, "scoringPeriodId": period["move"], "items": [
            {"playerId": add["id"], "type": "ADD", "toTeamId": TEAM, "_name": sw["add"]},
            {"playerId": drop["id"], "type": "DROP", "fromTeamId": TEAM, "_name": sw["drop"]}], "_swap": sw})
    return bodies, problems


def describe(body):
    return f"{body['type']}: " + "; ".join(
        f"{i['_name']} {i['type']}" + (f" {i['fromLineupSlotId']}->{i['toLineupSlotId']}" if i["type"] == "LINEUP" else "")
        for i in body["items"])


def clean(body):
    """Request body without our bookkeeping keys."""
    return {k: ([{kk: vv for kk, vv in i.items() if not kk.startswith("_")} for i in v] if k == "items" else v)
            for k, v in body.items() if not k.startswith("_")}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd not in ("apply", "swap", "add"):
        sys.exit(__doc__)
    dry = "--dry-run" in sys.argv
    if cmd == "add":
        names = [a for a in sys.argv[2:] if a != "--dry-run"]
        roster, pool, period, member = read_state()
        code, settings = request(READ + "?view=mSettings")
        slots = settings["settings"]["rosterSettings"]["lineupSlotCounts"]
        open_spots = sum(v for k, v in slots.items() if k != str(SLOT["IR"])) - sum(1 for r in roster.values() if r["slot"] != SLOT["IR"])
        result = {"did": [], "skipped": []}
        for name in names:
            add = pool.get(norm(name)) or pool.get(name)
            if not add:
                result["skipped"].append(f"{name}: not a free agent or on waivers"); continue
            if open_spots <= 0:
                result["skipped"].append(f"{name}: no open roster spot (add/drop instead)"); continue
            kind = "WAIVER" if add["status"] == "WAIVERS" else "FREEAGENT"
            body = {"isLeagueManager": False, "teamId": TEAM, "executionType": "EXECUTE", "memberId": member, "type": kind,
                    "scoringPeriodId": period["move"], "items": [{"playerId": add["id"], "type": "ADD", "toTeamId": TEAM, "_name": name}]}
            if dry:
                print(f"(dry run) would POST {WRITE}\n{json.dumps(clean(body), indent=1)}")
                result["did"].append("(dry run) " + describe(body)); open_spots -= 1; continue
            code, resp = request(WRITE, clean(body))
            with WRITE_LOG.open("a") as f:
                f.write(f"{datetime.now().isoformat()} {code} {describe(body)}\n  request {json.dumps(clean(body))}\n  response {json.dumps(resp)[:1500]}\n")
            status = resp.get("status") or next((t.get("status") for t in resp.get("transactions", [])), None)
            if code == 200 and status in ("EXECUTED", "PENDING"):
                result["did"].append(f"{describe(body)} ({status.lower()})"); open_spots -= 1
                subprocess.run([sys.executable, str(REPO / "manage.py"), "--league", "espn", "acq", name, "(open spot)"],
                               cwd=REPO, capture_output=True)
            else:
                err = resp.get("messages") or resp.get("details") or resp
                result["skipped"].append(f"{describe(body)}: ESPN said HTTP {code} {status or ''} {json.dumps(err)[:200]}")
        print("DID:", *result["did"] or ["nothing"], sep="\n  ")
        if result["skipped"]:
            print("SKIPPED:", *result["skipped"], sep="\n  ")
        print("\nRESULT_JSON " + json.dumps(result))
        return
    if cmd == "swap":
        args = [a for a in sys.argv[2:] if a != "--dry-run"]
        plan = {"lineup": {}, "ir": [], "swaps": [{"add": args[0], "drop": args[1], "gain": 0, "approved": True}]}
    else:
        text, plan = report_plan()
        print(text)
    roster, pool, period, member = read_state()
    bodies, problems = build(plan, roster, pool, period, member)
    result = {"did": [], "skipped": problems, "plan": plan, "period": period}
    WRITE_LOG.parent.mkdir(parents=True, exist_ok=True)
    for body in bodies:
        what = describe(body)
        if dry:
            print(f"\n(dry run) would POST {WRITE}\n{json.dumps(clean(body), indent=1)}")
            result["did"].append("(dry run) " + what)
            continue
        code, resp = request(WRITE, clean(body))
        with WRITE_LOG.open("a") as f:
            f.write(f"{datetime.now().isoformat()} {code} {what}\n  request {json.dumps(clean(body))}\n  response {json.dumps(resp)[:1500]}\n")
        status = resp.get("status") or next((t.get("status") for t in resp.get("transactions", [])), None)
        if code == 200 and status in ("EXECUTED", "PENDING"):
            result["did"].append(f"{what} ({status.lower()})")
            if "_swap" in body:
                sw = body["_swap"]
                subprocess.run([sys.executable, str(REPO / "manage.py"), "--league", "espn", "acq", sw["add"], sw["drop"]]
                               + ([] if sw.get("approved") else ["--auto"]), cwd=REPO, capture_output=True)
        else:
            err = resp.get("messages") or resp.get("details") or resp.get("raw") or resp
            result["skipped"].append(f"{what}: ESPN said HTTP {code} {status or ''} {json.dumps(err)[:200]}")
    if result["did"] and not dry and cmd == "apply":  # verify: a fresh report should have nothing left for what we sent
        _, plan2 = report_plan()
        left = plan2["lineup"] or plan2["ir"] or plan2["swaps"]
        result["left_after"] = plan2 if left else None
    print("\nDID:", *result["did"] or ["nothing"], sep="\n  ")
    if result["skipped"]:
        print("SKIPPED:", *result["skipped"], sep="\n  ")
    print("\nRESULT_JSON " + json.dumps(result))


if __name__ == "__main__":
    main()
