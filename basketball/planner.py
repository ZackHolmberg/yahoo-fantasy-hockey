"""Exact slot matching and schedule-aware lineup, streaming and trade planning."""
from datetime import date, timedelta
import math

from .config import INACTIVE, active_slots, instant, roster_size
from .model import totals


def assign(players, slots, values=None):
    """Rectangular Hungarian assignment: maximize filled slots, then player value.

    Dummy columns represent empty slots. A data-derived cardinality bonus exceeds
    every possible value tradeoff. Duplicate UTIL slots remain distinct rows.
    """
    values = values or {p["id"]: p.get("value", 0) for p in players}
    if any(not math.isfinite(v) for v in values.values()):
        raise ValueError("Player values must be finite")
    rows, cols = len(slots), len(players) + len(slots)
    bonus = 1 + sum(abs(v) for v in values.values())
    forbidden = bonus * (rows + cols + 1)
    costs = [[-bonus - values[p["id"]] if slot in p["eligible"] else forbidden for p in players] + [0] * rows for slot in slots]
    u, v, owner, previous = [0] * (rows + 1), [0] * (cols + 1), [0] * (cols + 1), [0] * (cols + 1)
    for row in range(1, rows + 1):
        owner[0], column = row, 0
        minimum, seen = [float("inf")] * (cols + 1), [False] * (cols + 1)
        while True:
            seen[column] = True
            current, delta, next_column = owner[column], float("inf"), 0
            for j in range(1, cols + 1):
                if seen[j]:
                    continue
                reduced = costs[current - 1][j - 1] - u[current] - v[j]
                if reduced < minimum[j]:
                    minimum[j], previous[j] = reduced, column
                if minimum[j] < delta:
                    delta, next_column = minimum[j], j
            for j in range(cols + 1):
                if seen[j]:
                    u[owner[j]] += delta
                    v[j] -= delta
                else:
                    minimum[j] -= delta
            column = next_column
            if not owner[column]:
                break
        while column:
            before = previous[column]
            owner[column] = owner[before]
            column = before
    return {players[j - 1]["id"]: slots[owner[j] - 1] for j in range(1, len(players) + 1)
            if owner[j] and slots[owner[j] - 1] in players[j - 1]["eligible"]}


def legal_roster(players, cfg):
    if len({p["id"] for p in players}) != len(players):
        return False
    if sum(p.get("slot") != "IR" for p in players) > roster_size(cfg):
        return False
    if sum(p.get("slot") == "IR" for p in players) > cfg["slots"].get("IR", 0):
        return False
    return all(sum(p["primary"] == pos for p in players if p.get("slot") != "IR") <= limit
               for pos, limit in cfg.get("position_limits", {}).items())


def preserves_coverage(before, after, cfg):
    usable = lambda ps: [p for p in ps if p.get("slot") != "IR"]
    slots = active_slots(cfg)
    return len(assign(usable(after), slots)) >= len(assign(usable(before), slots))


def games_on(snapshot, p, day):
    return [g for g in snapshot.get("games", {}).get(p["team"], []) if g["date"] == day and not g.get("cancelled")]


def healthy(p, cfg):
    return p["status"] not in INACTIVE and p["id"] not in cfg.get("do_not_start", []) and p["name"] not in cfg.get("do_not_start", [])


def lineup(model, day, roster=None, at=None, weights=None, respect_locks=True):
    """Honor started players in their current slots; never consume IR as a bench."""
    cfg, snap = model.cfg, model.snapshot
    roster = model.roster() if roster is None else roster
    slots = active_slots(cfg)
    fixed = {}
    if at is not None and respect_locks:
        for p in roster:
            started = any(instant(g["start"]) <= at for g in games_on(snap, p, day))
            if started and p.get("slot") not in {None, "BE", "IR"}:
                if p["slot"] not in slots:
                    raise ValueError("Locked lineup has more players than configured slots")
                slots.remove(p["slot"])
                fixed[p["id"]] = p["slot"]
    candidates = []
    for p in roster:
        if p["id"] in fixed or p.get("slot") == "IR" or not healthy(p, cfg):
            continue
        games = games_on(snap, p, day)
        if not games or (at is not None and respect_locks and any(instant(g["start"]) <= at for g in games)):
            continue
        candidates.append(p)
    values = {p["id"]: model.score(p, weights) * (0.7 if p["status"] in {"DAY_TO_DAY", "DTD"} else 1) for p in candidates}
    selected = fixed | assign(candidates, slots, values)
    return selected


def horizon(model, start, days=7, roster=None, at=None, weights=None, caps_used=None, remaining_only=False):
    cfg = model.cfg
    roster = model.roster() if roster is None else roster
    counts, plans = {p["id"]: 0 for p in roster}, {}
    used = dict(caps_used if caps_used is not None else model.snapshot.get("games_used", {}))
    caps = cfg.get("games_caps", {})
    if caps and caps_used is None and "games_used" not in model.snapshot:
        raise ValueError("Games caps configured but snapshot.games_used is missing; refusing to guess remaining capacity")
    if cfg["lineup_lock"] == "weekly":
        totals_by_id = {p["id"]: sum(bool(games_on(model.snapshot, p, (start + timedelta(days=d)).isoformat())) for d in range(days)) * model.score(p, weights) for p in roster}
        selection = assign([p for p in roster if p.get("slot") != "IR" and healthy(p, cfg)], active_slots(cfg), totals_by_id)
    else:
        selection = None
    for offset in range(days):
        day = (start + timedelta(days=offset)).isoformat()
        plan = dict(selection) if selection is not None else lineup(model, day, roster, at if offset == 0 else None, weights)
        for pid, slot in sorted(plan.items(), key=lambda item: -model.score(model.by_id[item[0]], weights)):
            p = model.by_id[pid]
            if not games_on(model.snapshot, p, day):
                del plan[pid]
                continue
            key = "ALL" if "ALL" in caps else slot
            if key in caps and used.get(key, 0) >= caps[key]:
                del plan[pid]
                continue
            games = games_on(model.snapshot, p, day)
            if remaining_only and at is not None:
                games = [g for g in games if instant(g["start"]) > at]
            allowed = min(len(games), max(0, caps[key] - used.get(key, 0))) if key in caps else len(games)
            counts[pid] += allowed
            used[key] = used.get(key, 0) + allowed
        plans[day] = plan
    projected = totals(roster, counts)
    if cfg["format"] == "points":
        value = sum(projected.get(k, 0) * w for k, w in cfg["scoring"].items())
    else:
        value = sum(model.score(p, weights) * counts[p["id"]] for p in roster)
    return {"value": round(value, 3), "totals": projected, "games": counts, "lineups": plans, "caps_used": used}


def roster_value(model, players):
    """Best season lineup with replacement-level credit for empty positions."""
    pool = [p for p in players if p["ranked"] and healthy(p, model.cfg)]
    owned_ids = {p["id"] for p in players}
    available = [p for p in model.available() if p["id"] not in owned_ids and p["ranked"] and healthy(p, model.cfg)]
    candidates = pool + available
    chosen = assign(candidates, active_slots(model.cfg), {p["id"]: p["value"] * p["remaining_games"] for p in candidates})
    return sum(model.by_id[pid]["value"] * model.by_id[pid]["remaining_games"] for pid in chosen)


def trade(model, give, get, other):
    mine, theirs = model.roster(), model.roster(other)
    give = [model.find(n, mine) for n in give]
    get = [model.find(n, theirs) for n in get]
    if not give or not get or len({p["id"] for p in give + get}) != len(give + get):
        raise ValueError("Trade requires unique players on both sides")
    ours = [p for p in mine if p not in give] + [dict(p, slot="BE") for p in get]
    theirs_after = [p for p in theirs if p not in get] + [dict(p, slot="BE") for p in give]
    if not legal_roster(ours, model.cfg) or not legal_roster(theirs_after, model.cfg):
        raise ValueError("Trade exceeds a roster or position limit; specify the necessary drops separately")
    a = roster_value(model, ours) - roster_value(model, mine)
    b = roster_value(model, theirs_after) - roster_value(model, theirs)
    return {"give": [p["name"] for p in give], "get": [p["name"] for p in get], "team": other,
            "our_gain": round(a, 2), "their_gain": round(b, 2), "good_for_both": a > 0 and b > 0}


def trade_ideas(model, limit=5):
    ideas = []
    for t in model.snapshot["teams"]:
        if t["id"] == model.cfg["team_id"]:
            continue
        for a in model.roster():
            if not a["ranked"] or not healthy(a, model.cfg) or a["id"] in model.cfg.get("protected", []):
                continue
            for b in model.roster(t["id"]):
                if not b["ranked"] or not healthy(b, model.cfg):
                    continue
                try:
                    proposal = trade(model, [a["id"]], [b["id"]], t["id"])
                except ValueError:
                    continue
                if proposal["good_for_both"]:
                    ideas.append(proposal)
    return sorted(ideas, key=lambda t: -min(t["our_gain"], t["their_gain"]))[:limit]


def acquisitions_used(model):
    team = next(t for t in model.snapshot["teams"] if t["id"] == model.cfg["team_id"])
    return team.get("acquisitions")


def moves(model, start, days=7, streaming=False, weights=None, limit=10, at=None):
    mine, cfg = model.roster(), model.cfg
    base = horizon(model, start, days, at=at, weights=weights, remaining_only=at is not None) if streaming else None
    protected = set(cfg.get("protected", []))
    drops = [p for p in mine if p.get("slot") != "IR" and not p.get("undroppable") and p["id"] not in protected and p["name"] not in protected]
    if at is not None and start == at.date():
        drops = [p for p in drops if not any(instant(g["start"]) <= at for g in games_on(model.snapshot, p, start.isoformat()))]
    empty = roster_size(cfg) - sum(p.get("slot") != "IR" for p in mine)
    if empty > 0:
        drops.append(None)
    result = []
    for add in model.available():
        if not add["ranked"] or not healthy(add, cfg):
            continue
        best = None
        for drop in drops:
            ros_gain = add["value"] * add["remaining_games"] - (drop["value"] * drop["remaining_games"] if drop else 0)
            if not streaming and ros_gain <= 0:
                continue
            roster = [p for p in mine if drop is None or p["id"] != drop["id"]] + [dict(add, slot="BE")]
            if not legal_roster(roster, cfg) or not preserves_coverage(mine, roster, cfg):
                continue
            if streaming:
                # Waiver players cannot produce points until their claim clears.
                eligible_start = start + timedelta(days=math.ceil(cfg.get("waiver_days", 1))) if add["availability"] == "WAIVERS" else start
                delay = min(days, (eligible_start - start).days)
                before = horizon(model, start, delay, mine, at=at, weights=weights, remaining_only=at is not None)
                after = horizon(model, eligible_start, days - delay, roster, at=at, weights=weights, caps_used=before["caps_used"], remaining_only=at is not None)
                gain = before["value"] + after["value"] - base["value"]
            else:
                gain = ros_gain
            item = {"add": add["id"], "add_name": add["name"], "drop": drop["id"] if drop else None,
                    "drop_name": drop["name"] if drop else None, "gain": round(gain, 2), "ros_gain": round(ros_gain, 2),
                    "waiver": add["availability"] == "WAIVERS"}
            if best is None or gain > best["gain"]:
                best = item
        if best and best["gain"] > 0:
            result.append(best)
    return sorted(result, key=lambda m: -m["gain"])[:limit]
