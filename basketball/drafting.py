"""Snake/auction draft state, ESPN pick sync, ADP timing, and budget discipline."""
import math
import re
import unicodedata

from .config import active_slots, path, read_json, roster_size, write_json
from .planner import assign, legal_roster


def state(model):
    saved = read_json(path(model.cfg, "draft.json"), {"picks": []})
    return saved


def normalize_name(name):
    return "".join(c for c in unicodedata.normalize("NFKD", name.casefold()) if not unicodedata.combining(c))


def sync(model):
    saved = state(model)
    picks = model.snapshot.get("draft", {}).get("picks", [])
    if not picks:
        return {"synced": 0, "message": "No ESPN draft picks returned yet; manual tracking remains available."}
    imported = [{"player": int(p["playerId"]), "team": int(p["teamId"]),
                 "pick": p.get("overallPickNumber", i + 1), "cost": p.get("bidAmount", 0), "source": "espn"}
                for i, p in enumerate(picks) if p.get("playerId") and p.get("teamId")]
    manual = [p for p in saved["picks"] if p.get("source") != "espn" and p["player"] not in {x["player"] for x in imported}]
    saved["picks"] = sorted(imported + manual, key=lambda p: p["pick"])
    write_json(path(model.cfg, "draft.json"), saved)
    return {"synced": len(imported), "total": len(saved["picks"])}


def record(model, names, team=None, cost=0, undo=False, paste=False):
    saved = state(model)
    if cost < 0:
        raise ValueError("Auction cost cannot be negative")
    if paste:
        text = normalize_name(" ".join(names))
        names = [p["id"] for p in model.players if re.search(r"(?<!\w)" + re.escape(normalize_name(p["name"])) + r"(?!\w)", text)]
    for name in names:
        p = model.find(name)
        existing = [x for x in saved["picks"] if x["player"] == p["id"]]
        if undo:
            saved["picks"] = [x for x in saved["picks"] if x["player"] != p["id"]]
        elif existing:
            if team is not None:
                existing[0]["team"] = team
            if cost:
                existing[0]["cost"] = cost
        else:
            saved["picks"].append({"player": p["id"], "team": team or 0,
                                   "cost": cost, "pick": max((x["pick"] for x in saved["picks"]), default=0) + 1,
                                   "source": "manual"})
    write_json(path(model.cfg, "draft.json"), saved)
    return {"recorded": len(names), "picks": len(saved["picks"])}


def snake_picks(teams, slot, rounds):
    return [r * teams + (slot if r % 2 == 0 else teams + 1 - slot) for r in range(rounds)]


def survival(adp, current, next_pick, sigma):
    if not adp or not next_pick:
        return None
    sigma = max(1, sigma)
    tail = lambda pick: 0.5 * math.erfc((pick - float(adp)) / (sigma * math.sqrt(2)))
    return round(min(1, tail(next_pick) / max(1e-12, tail(current))), 3)


def rankings(model):
    cfg = model.cfg
    slots = active_slots(cfg)
    ranked = sorted((p for p in model.players if p["ranked"]), key=lambda p: -p["value"] * p["projected_games"])
    replacement = {}
    primary = {"PG", "SG", "SF", "PF", "C"}
    allowed = {"PG": {"PG"}, "SG": {"SG"}, "SF": {"SF"}, "PF": {"PF"}, "C": {"C"},
               "G": {"PG", "SG"}, "F": {"SF", "PF"}, "SG/SF": {"SG", "SF"},
               "G/F": primary - {"C"}, "PF/C": {"PF", "C"}, "F/C": {"SF", "PF", "C"},
               "UTIL": primary, "BE": primary}
    # Distribute shared slots and bench depth across eligible primary positions.
    # Including UTIL as a competing replacement baseline would erase scarcity:
    # every NBA player can use it. This approximation is explicit and deterministic.
    for s in primary:
        eligible = [p for p in ranked if s in p["eligible"]]
        depth = cfg["teams"] * sum(n / len(allowed[slot]) for slot, n in cfg["slots"].items() if slot in allowed and s in allowed[slot])
        repl = eligible[min(len(eligible) - 1, max(0, math.ceil(depth)))] if eligible else None
        replacement[s] = repl["value"] * repl["projected_games"] if repl else 0
    rows = []
    for p in ranked:
        if not any(s in p["eligible"] for s in slots):
            continue
        eligible = [s for s in primary if s in p["eligible"]] or [p["primary"]]
        vor = max(p["value"] * p["projected_games"] - replacement[s] for s in eligible)
        rows.append({"id": p["id"], "name": p["name"], "eligible": p["eligible"],
                     "fpg": round(p["fpg"], 2), "value": round(p["value"], 3),
                     "vor": round(vor, 3), "projected_games": p["projected_games"],
                     "status": p["status"], "source": p["projection_source"], "adp": p.get("adp")})
    rows.sort(key=lambda p: -p["vor"])
    return rows


def board(model, count=20, current=None, slot=None):
    cfg, saved = model.cfg, state(model)
    gone = {p["player"] for p in saved["picks"]}
    unknown = [pid for pid in gone if pid not in model.by_id]
    mine = [model.by_id[p["player"]] for p in saved["picks"] if p["team"] == cfg["team_id"] and p["player"] in model.by_id]
    remaining = roster_size(cfg) - len(mine)
    current = current or max((p["pick"] for p in saved["picks"]), default=0) + 1
    slot = slot or cfg["draft"].get("slot")
    if slot is not None and not 1 <= slot <= cfg["teams"]:
        raise ValueError("Draft slot is outside league size")
    next_pick = next((p for p in snake_picks(cfg["teams"], slot, roster_size(cfg)) if p > current), None) if slot else None
    slots, rows = active_slots(cfg), []
    if unknown:
        raise ValueError("Draft has players missing from this snapshot; refresh the full player pool before recommending picks")
    for row in rankings(model):
        p = model.by_id[row["id"]]
        if p["id"] in gone or p["owner"] not in (0, cfg["team_id"]) or remaining <= 0:
            continue
        prospective = [dict(q, slot="BE") for q in mine + [p]]
        if not legal_roster(prospective, cfg):
            continue
        matching = assign(prospective, slots)
        missing = len(slots) - len(matching)
        if missing > remaining - 1:
            continue
        rows.append({**row, "available_next_pick": survival(p.get("adp"), current, next_pick, cfg["draft"].get("adp_sigma", 12))})
    filled = assign(mine, slots)
    missing = list(slots)
    for s in filled.values():
        missing.remove(s)
    return {"pick": current, "next_pick": next_pick, "remaining_roster_spots": remaining,
            "unfilled_starters": missing, "unmatched_drafted_ids": unknown,
            "availability_note": "Conditional ADP heuristic; not a calibrated prediction.", "players": rows[:count]}


def auction(model, name, current_bid=0):
    cfg, saved = model.cfg, state(model)
    if current_bid < 0:
        raise ValueError("Current auction bid cannot be negative")
    p = model.find(name)
    if p["id"] in {x["player"] for x in saved["picks"]}:
        raise ValueError("Player is already drafted")
    own = [x for x in saved["picks"] if x["team"] == cfg["team_id"]]
    spots = roster_size(cfg) - len(own)
    if spots <= 0:
        raise ValueError("Roster is full")
    budget, minimum = cfg["draft"]["budget"], cfg["draft"].get("minimum_bid", 1)
    cash = budget - sum(x.get("cost", 0) for x in own)
    max_legal = max(0, cash - minimum * (spots - 1))
    ranked = board(model, count=len(model.players))["players"]
    row = next((r for r in ranked if r["id"] == p["id"]), None)
    if not row:
        raise ValueError("Player cannot fit the remaining roster/position requirements or has no projection")
    taken = {x["player"] for x in saved["picks"]}
    eligible = [r for r in rankings(model) if r["id"] not in taken][:cfg["teams"] * roster_size(cfg) - len(saved["picks"])]
    surplus = sum(max(0, r["vor"]) for r in eligible)
    spent = sum(x.get("cost", 0) for x in saved["picks"])
    league_spots = cfg["teams"] * roster_size(cfg) - len(saved["picks"])
    discretionary = max(0, cfg["teams"] * budget - spent - minimum * league_spots)
    fair = minimum + discretionary * max(0, row["vor"]) / surplus if surplus else minimum
    maximum = min(max_legal, max(minimum, round(fair)))
    bid = max(minimum, current_bid + minimum)
    return {"id": p["id"], "name": p["name"], "cash": cash, "spots": spots,
            "fair_value": round(fair, 2), "maximum_bid": maximum,
            "next_bid": bid if bid <= maximum else None, "market_value": p.get("auction_value")}
