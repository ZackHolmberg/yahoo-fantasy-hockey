"""Reports and mutation planning. ESPN is authoritative for ownership and budgets."""
from contextlib import contextmanager
from datetime import date, timedelta
import hashlib

from .config import (INACTIVE, SLOT_IDS, active_slots, credentials, identity, instant,
                     now, path, read_json, roster_size, write_json)
from .espn import Client
from .model import Model, totals
from .planner import (acquisitions_used, assign, games_on, healthy, horizon,
                      legal_roster, lineup, moves, preserves_coverage, trade)


@contextmanager
def run_lock(cfg):
    lock = path(cfg, ".lock")
    lock.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ValueError(f"Another basketball run holds {lock}; inspect it before removing a stale lock") from exc
    try:
        yield
    finally:
        lock.rmdir()


def ledger(cfg):
    return read_json(path(cfg, "transactions.json"), [])


def pending_ids(cfg):
    return {i["playerId"] for r in ledger(cfg) if r["state"] in {"PENDING", "UNKNOWN", "SENDING", "ACKNOWLEDGED"}
            for i in r["body"]["items"]}


def pending_players(model):
    tid = model.cfg["team_id"]
    return pending_ids(model.cfg) | {i["playerId"] for t in model.snapshot.get("pending", [])
            if t.get("teamId") == tid or any(x.get("fromTeamId") == tid or x.get("toTeamId") == tid for x in t.get("items", []))
            for i in t.get("items", []) if "playerId" in i}


def matchup_bounds(model, day):
    settings = model.snapshot.get("settings", {}).get("scheduleSettings", {})
    periods = settings.get("matchupPeriods", {})
    current = model.snapshot.get("matchup_period")
    ids = periods.get(str(current), periods.get(current, []))
    days = sorted({g["date"] for rows in model.snapshot.get("games", {}).values() for g in rows if g.get("period") in ids})
    if days:
        return date.fromisoformat(days[0]), date.fromisoformat(days[-1])
    # Offline snapshots may omit ESPN period boundaries. Reports label this fallback.
    return day - timedelta(days=day.weekday()), day + timedelta(days=6 - day.weekday())


def opponent(model):
    for matchup in model.snapshot.get("matchups", []):
        if matchup.get("matchupPeriodId") != model.snapshot.get("matchup_period"):
            continue
        home, away = matchup.get("home", {}), matchup.get("away", {})
        if home.get("teamId") == model.cfg["team_id"]:
            return away.get("teamId"), home, away
        if away.get("teamId") == model.cfg["team_id"]:
            return home.get("teamId"), away, home
    return None, {}, {}


def scored_totals(side):
    from .espn import stats
    raw = side.get("cumulativeScore", {}).get("scoreByStat", {})
    return stats({k: v.get("score", 0) if isinstance(v, dict) else v for k, v in raw.items()})


def matchup_report(model, day):
    team, us, them = opponent(model)
    if not team:
        return {"available": False, "reason": "No current opponent in the ESPN snapshot"}
    start, end = matchup_bounds(model, day)
    start = max(start, day)
    days = max(1, (end - start).days + 1)
    at = now(model.cfg)
    a = horizon(model, start, days, at=at, remaining_only=True)
    b = horizon(model, start, days, model.roster(team), at=at, remaining_only=True)
    ours, theirs = a["totals"], b["totals"]
    for current, projected in ((scored_totals(us), ours), (scored_totals(them), theirs)):
        for k, v in current.items():
            if k not in {"FG%", "FT%", "3PT%"}:
                projected[k] = projected.get(k, 0) + v
        for cat, (made, att) in {"FG%": ("FGM", "FGA"), "FT%": ("FTM", "FTA"), "3PT%": ("3PM", "3PA")}.items():
            projected[cat] = projected.get(made, 0) / projected[att] if projected.get(att) else 0
    comparison = model.compare(ours, theirs)
    if model.cfg["format"] == "points":
        comparison["ours"] = round(comparison["ours"] + us.get("totalPoints", 0), 2)
        comparison["theirs"] = round(comparison["theirs"] + them.get("totalPoints", 0), 2)
        comparison["margin"] = round(comparison["ours"] - comparison["theirs"], 2)
    return {"available": True, "opponent": team, "through": end.isoformat(),
            "comparison": comparison, "target_weights": model.target_weights(ours, theirs),
            "note": "Remaining scheduled games plus available cumulative stats; opponent future lineup is modeled."}


def complete_lineup(model, day, at, roster):
    selected = lineup(model, day, roster, at)
    if model.cfg.get("games_caps"):
        selected = horizon(model, date.fromisoformat(day), 1, roster, at=at)["lineups"][day]
    slots = active_slots(model.cfg)
    for s in selected.values():
        slots.remove(s)
    remaining = []
    locked_bench = set()
    for p in roster:
        if p["id"] in selected or p.get("slot") == "IR":
            continue
        if p.get("slot") == "BE" and any(instant(g["start"]) <= at for g in games_on(model.snapshot, p, day)):
            locked_bench.add(p["id"])
        else:
            remaining.append(p)
    fillers = assign(remaining, slots, {p["id"]: 0 for p in remaining})
    selected.update(fillers)
    targets = {p["id"]: selected.get(p["id"], "BE") for p in roster if p.get("slot") != "IR"}
    if sum(s == "BE" for s in targets.values()) > model.cfg["slots"].get("BE", 0):
        raise ValueError("Cannot create a legal lineup with current eligibility and locked bench players")
    return targets


def report(model, day=None, at=None):
    cfg = model.cfg
    at = at or now(cfg)
    day = day or at.date()
    roster = model.roster()
    if model.snapshot.get("draft_complete") is False or not roster:
        return {**identity(cfg), "date": day.isoformat(), "fetched_at": model.snapshot["fetched_at"],
                "lineup": [], "moves": [], "auto_move": None, "acquisitions_used": None,
                "issues": ["The roster is empty or the draft is not completed; use draft best/sync."], "matchup": {"available": False}}
    issues, ir, targets = [], [], {}
    working = [dict(p) for p in roster]
    ir_count = sum(p.get("slot") == "IR" for p in working)
    non_ir = sum(p.get("slot") != "IR" for p in working)
    for p in working:
        locked = any(instant(g["start"]) <= at for g in games_on(model.snapshot, p, day.isoformat()))
        if locked:
            continue
        if p["status"] in cfg.get("ir_statuses", []) and "IR" in p["eligible"] and p.get("slot") != "IR" and ir_count < cfg["slots"].get("IR", 0):
            ir.append(p["id"])
            p["slot"] = "IR"
            ir_count += 1
            non_ir -= 1
        elif p.get("slot") == "IR" and p["status"] not in cfg.get("ir_statuses", []):
            if non_ir < roster_size(cfg):
                p["slot"] = "BE"
                non_ir += 1
                ir_count -= 1
            else:
                issues.append(f"{p['name']} is healthy in IR; activation needs a roster opening")
    if cfg["lineup_lock"] == "daily":
        targets = complete_lineup(model, day.isoformat(), at, working)
    else:
        start, end = matchup_bounds(model, day)
        week_start = min((g["start"] for rows in model.snapshot.get("games", {}).values() for g in rows
                          if start.isoformat() <= g["date"] <= end.isoformat()), default=None)
        if week_start and instant(week_start) <= at:
            issues.append("Weekly lineup is locked")
            ir = []
        else:
            plan = horizon(model, start, max(1, (end - start).days + 1), working)
            chosen = {}
            for entries in plan["lineups"].values():
                chosen.update(entries)
            slots = active_slots(cfg)
            for slot in chosen.values():
                slots.remove(slot)
            spare = [p for p in working if p["id"] not in chosen and p.get("slot") != "IR"]
            chosen.update(assign(spare, slots, {p["id"]: 0 for p in spare}))
            targets = {p["id"]: chosen.get(p["id"], "BE") for p in working if p.get("slot") != "IR"}
    targets.update({pid: "IR" for pid in ir})
    changes = [{"player": p["id"], "name": p["name"], "from": p["slot"], "to": targets[p["id"]]}
               for p in roster if p["id"] in targets and p["slot"] != targets[p["id"]]]
    used = acquisitions_used(model)
    history = ledger(cfg)
    auto_used = sum(r.get("auto", False) and r.get("matchup") == model.snapshot.get("matchup_period") and r["state"] in {"PENDING", "EXECUTED", "ACKNOWLEDGED"}
                    for r in history if r["body"]["type"] in {"FREEAGENT", "WAIVER"})
    candidates = moves(model, day, at=at)
    blocked = pending_players(model)
    candidates = [m for m in candidates if m["add"] not in blocked and m["drop"] not in blocked]
    auto_left = max(0, cfg.get("auto_adds", 0) - auto_used)
    league_left = max(0, cfg["acquisition_limit"] - used) if used is not None and cfg.get("acquisition_limit") is not None else (auto_left if used is not None else 0)
    for m in candidates:
        key = f"{cfg['league_id']}:{cfg['team_id']}:{cfg['season']}:{m['add']}:{m['drop']}"
        m["proposal"] = "B" + hashlib.sha256(key.encode()).hexdigest()[:8]
        m["auto"] = auto_left > 0 and league_left > 0 and m["ros_gain"] >= cfg.get("min_ros_gain", 100)
    if used is None:
        issues.append("ESPN acquisition count is unavailable; automatic adds are disabled")
    return {**identity(cfg), "date": day.isoformat(), "fetched_at": model.snapshot["fetched_at"],
            "lineup": changes, "moves": candidates, "auto_move": next((m for m in candidates if m["auto"]), None),
            "acquisitions_used": used, "auto_left": auto_left, "league_left": league_left,
            "issues": issues, "matchup": matchup_report(model, day),
            "note": "At most one automatic acquisition per run; every executed run refreshes ESPN first."}


def envelope(model, kind):
    auth = credentials(model.cfg)
    period = model.snapshot["period"] if kind == "ROSTER" else model.snapshot["transaction_period"]
    if period is None:
        raise ValueError("ESPN scoring/transaction period is unavailable")
    return {"isLeagueManager": False, "teamId": model.cfg["team_id"], "memberId": auth.get("SWID", ""),
            "executionType": "EXECUTE", "type": kind, "scoringPeriodId": period, "items": []}


def lineup_body(model, changes):
    body = envelope(model, "ROSTER")
    for change in changes:
        p = model.find(change["player"], model.roster())
        if p["slot"] != change["from"] or change["to"] not in p["eligible"]:
            raise ValueError(f"Stale or illegal lineup move for {p['name']}")
        body["items"].append({"playerId": p["id"], "type": "LINEUP", "fromTeamId": model.cfg["team_id"],
                              "toTeamId": model.cfg["team_id"], "fromLineupSlotId": SLOT_IDS[p["slot"]],
                              "toLineupSlotId": SLOT_IDS[change["to"]]})
    return body


def swap_body(model, add_name, drop_name=None, approved=False, bid=None):
    cfg = model.cfg
    if model.snapshot.get("draft_complete") is False:
        raise ValueError("ESPN draft is not completed; acquisitions are unavailable")
    add = model.find(add_name, model.available())
    drop = model.find(drop_name, model.roster()) if drop_name is not None else None
    if drop and drop.get("undroppable"):
        raise ValueError("ESPN marks the dropped player undroppable")
    if not approved and drop and (drop["id"] in cfg.get("protected", []) or drop["name"] in cfg.get("protected", [])):
        raise ValueError("Automatic moves cannot drop protected players")
    roster = [p for p in model.roster() if not drop or p["id"] != drop["id"]] + [dict(add, slot="BE")]
    if not legal_roster(roster, cfg) or not preserves_coverage(model.roster(), roster, cfg):
        raise ValueError("Acquisition exceeds roster/position limits or loses starting-position coverage")
    at = now(cfg)
    if drop and any(instant(g["start"]) <= at for g in games_on(model.snapshot, drop, at.date().isoformat())):
        raise ValueError("The dropped player's game has started; retry after the scoring period changes")
    used = acquisitions_used(model)
    if used is None:
        raise ValueError("ESPN acquisition count is unknown; refresh before making acquisitions")
    if cfg.get("acquisition_limit") is not None and used >= cfg["acquisition_limit"]:
        raise ValueError("Matchup acquisition limit reached")
    season_limit = cfg.get("season_acquisition_limit")
    if season_limit is not None:
        team = next(t for t in model.snapshot["teams"] if t["id"] == cfg["team_id"])
        if team.get("season_acquisitions") is None or team["season_acquisitions"] >= season_limit:
            raise ValueError("Season acquisition limit reached or usage unknown")
    if {add["id"], drop["id"] if drop else None} & pending_players(model):
        raise ValueError("A pending/unverified transaction already involves these players")
    kind = "WAIVER" if add["availability"] == "WAIVERS" else "FREEAGENT"
    body = envelope(model, kind)
    body["items"] = [{"playerId": add["id"], "type": "ADD", "toTeamId": cfg["team_id"]}]
    if drop:
        body["items"].append({"playerId": drop["id"], "type": "DROP", "fromTeamId": cfg["team_id"]})
    if bid is not None:
        if kind != "WAIVER" or cfg.get("waiver_system") != "faab":
            raise ValueError("FAAB bids require a FAAB league and a player on waivers")
        team = next(t for t in model.snapshot["teams"] if t["id"] == cfg["team_id"])
        available = cfg.get("faab_budget", 0) - team.get("acquisition_budget_spent", 0)
        if bid < 0 or bid > available:
            raise ValueError("FAAB bid exceeds remaining budget")
        if bid < cfg.get("faab_minimum_bid", 0):
            raise ValueError("FAAB bid is below the league minimum")
        body["bidAmount"] = bid
    elif kind == "WAIVER" and cfg.get("waiver_system") == "faab":
        raise ValueError("Specify an explicit FAAB bid")
    return body


def trade_body(model, give, get, other):
    if other == model.cfg["team_id"]:
        raise ValueError("Cannot trade with your own team")
    if model.cfg.get("trade_deadline") and now(model.cfg) >= instant(model.cfg["trade_deadline"]):
        raise ValueError("Trade deadline has passed")
    trade(model, give, get, other)  # validates unique ownership and both roster limits
    body = envelope(model, "TRADE_PROPOSAL")
    for names, source, destination in ((give, model.cfg["team_id"], other), (get, other, model.cfg["team_id"])):
        for name in names:
            p = model.find(name, model.roster(source))
            if p["id"] in pending_ids(model.cfg):
                raise ValueError("An unverified/pending transaction already involves a trade player")
            body["items"].append({"playerId": p["id"], "type": "TRADE", "fromTeamId": source, "toTeamId": destination})
    body["expirationDate"] = int((now(model.cfg) + timedelta(days=7)).timestamp() * 1000)
    return body


def trade_response_body(model, offer_id, accept):
    offers = [t for t in model.snapshot.get("pending", []) if str(t.get("id")) == str(offer_id)
              and t.get("type") == "TRADE_PROPOSAL"]
    if len(offers) != 1:
        raise ValueError("Find exactly one pending trade proposal by its ESPN transaction ID")
    offer = offers[0]
    tid = model.cfg["team_id"]
    if offer.get("teamId") == tid or not any(i.get("toTeamId") == tid for i in offer.get("items", [])):
        raise ValueError("This is not an incoming trade offer for our team")
    other_ids = {i["fromTeamId"] for i in offer["items"] if i.get("toTeamId") == tid}
    if len(other_ids) != 1:
        raise ValueError("Only two-team player trades are supported")
    give = [i["playerId"] for i in offer["items"] if i.get("fromTeamId") == tid]
    get = [i["playerId"] for i in offer["items"] if i.get("toTeamId") == tid]
    if accept:
        trade_body(model, give, get, next(iter(other_ids)))  # current ownership/deadline/limits
    body = envelope(model, "TRADE_ACCEPT" if accept else "TRADE_DECLINE")
    body["relatedTransactionId"] = offer.get("relatedTransactionId") or offer["id"]
    body["items"] = [{k: i[k] for k in ("playerId", "type", "fromTeamId", "toTeamId")} for i in offer["items"]]
    return body


def verify_body(body, snapshot, cfg):
    if body["type"] == "TRADE_PROPOSAL":
        legs = lambda items: {(i.get("playerId"), i.get("fromTeamId"), i.get("toTeamId")) for i in items}
        return any(t.get("type") == "TRADE_PROPOSAL" and t.get("teamId") == cfg["team_id"] and legs(t.get("items", [])) == legs(body["items"])
                   for t in snapshot.get("pending", []))
    if body["type"] == "TRADE_DECLINE":
        return any(t.get("type") == "TRADE_DECLINE" and t.get("status") == "EXECUTED"
                   and t.get("relatedTransactionId") == body["relatedTransactionId"] and t.get("teamId") == cfg["team_id"]
                   for t in snapshot.get("transactions", []))
    by = {p["id"]: p for p in snapshot["players"]}
    for item in body["items"]:
        p = by.get(item["playerId"])
        if not p:
            return False
        if item["type"] == "LINEUP" and p.get("slot") != next(k for k, v in SLOT_IDS.items() if v == item["toLineupSlotId"]):
            return False
        if item["type"] == "ADD" and p["owner"] != cfg["team_id"]:
            return False
        if item["type"] == "DROP" and p["owner"] == cfg["team_id"]:
            return False
        if item["type"] == "TRADE" and p["owner"] != item["toTeamId"]:
            return False
    return True


def send_checked(model, body, auto=False):
    cfg = model.cfg
    if not credentials(cfg).get("SWID") or not credentials(cfg).get("espn_s2"):
        raise ValueError("Authenticated ESPN cookies are required to execute writes")
    history = ledger(cfg)
    if any(r["state"] in {"SENDING", "UNKNOWN"} for r in history):
        raise ValueError("A prior write has an unknown outcome. Run reconcile before issuing more writes")
    if body["type"] == "ROSTER" and any(r["body"]["type"] == "ROSTER" and r["state"] in {"PENDING", "ACKNOWLEDGED"} for r in history):
        raise ValueError("A previous lineup write is not verified; reconcile before resubmitting a lineup")
    record = {"at": now(cfg).isoformat(), "matchup": model.snapshot.get("matchup_period"),
              "auto": auto, "state": "SENDING", "body": body}
    # memberId is account data; keep it in memory, not the audit file.
    record["body"] = {k: v for k, v in body.items() if k != "memberId"}
    history.append(record)
    write_json(path(cfg, "transactions.json"), history)
    try:
        response = Client(cfg).send(body)
    except Exception:
        record["state"] = "UNKNOWN"
        write_json(path(cfg, "transactions.json"), history)
        raise
    record["state"] = "PENDING" if response["status"] == "PENDING" else "ACKNOWLEDGED"
    record["response"] = response
    write_json(path(cfg, "transactions.json"), history)
    snapshot = Client(cfg).fetch()
    verified = verify_body(body, snapshot, cfg)
    if verified:
        record["state"] = "PENDING" if body["type"] == "TRADE_PROPOSAL" else "EXECUTED"
        write_json(path(cfg, "transactions.json"), history)
    return {"state": record["state"], "response": response, "verified": verified}


def reconcile(cfg, snapshot):
    history = ledger(cfg)
    for r in history:
        if r["state"] in {"SENDING", "UNKNOWN", "ACKNOWLEDGED", "PENDING"} and verify_body(r["body"], snapshot, cfg):
            r["state"] = "PENDING" if r["body"]["type"] == "TRADE_PROPOSAL" else "EXECUTED"
    write_json(path(cfg, "transactions.json"), history)
    return [{"at": r["at"], "state": r["state"]} for r in history if r["state"] != "EXECUTED"]


def resolve_not_executed(cfg, snapshot, index):
    """Explicit owner attestation after inspecting ESPN activity/pending claims."""
    history = ledger(cfg)
    if index < 1 or index > len(history):
        raise ValueError("Use the one-based transaction index from the audit file")
    record = history[index - 1]
    if record["state"] not in {"UNKNOWN", "SENDING", "ACKNOWLEDGED", "PENDING"}:
        raise ValueError("Only unresolved transactions can be marked not executed")
    if verify_body(record["body"], snapshot, cfg):
        raise ValueError("Fresh ESPN state confirms this transaction; reconcile it instead")
    player_ids = {i["playerId"] for i in record["body"]["items"]}
    if any(player_ids & {i.get("playerId") for i in t.get("items", [])} for t in snapshot.get("pending", [])):
        raise ValueError("ESPN still lists a pending transaction for these players")
    record["state"], record["owner_resolved_at"] = "NOT_EXECUTED", now(cfg).isoformat()
    write_json(path(cfg, "transactions.json"), history)
    return {"index": index, "state": "NOT_EXECUTED"}
