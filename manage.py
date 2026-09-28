"""In-season team manager (companion to docs/MANAGER.md).

    python3 manage.py roster set "Name|POS|STATUS" ...   # replace my roster (POS as Yahoo shows it, e.g. LW,RW; STATUS e.g. IR, DTD, O or empty)
    python3 manage.py roster                             # show roster with rest-of-season value
    python3 manage.py eval "Name|POS|STATUS" ...         # rank free agents against my droppable players
    python3 manage.py acq "Add Name" "Drop Name" [--auto] # record a completed add/drop
    python3 manage.py week                               # acquisitions used this week (Mon-Sun)
    python3 manage.py log "text"                         # append a line to data/season_log.md

Stdlib only. Values come from data/rankings.csv (preseason model); unranked players get no value
and are never auto-added. Guardrails live in data/manager_rules.json.
"""
import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from draft import load_rankings, norm, resolve
from team_alias import scrub

STATE = Path("data/season_state.json")
RULES = json.loads(Path("data/manager_rules.json").read_text())
LOG = Path("data/season_log.md")
INJURED = {"IR", "IR-LT", "IR-NR", "O", "OUT", "INJ"}


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {"roster": [], "adds": []}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=2))


def season_left(today=None):
    today = today or date.today()
    start, end = (date.fromisoformat(RULES[k]) for k in ("season_start", "season_end"))
    return max(0.0, min(1.0, (end - max(today, start)).days / (end - start).days))


def parse(spec, rankings):
    """'Name|POS|STATUS' -> player dict with rest-of-season value."""
    parts = [p.strip() for p in spec.split("|")] + ["", ""]
    raw, pos, status = parts[0], parts[1].upper(), parts[2].upper()
    by_name = {r["name"]: r for r in rankings}
    exact = {norm(r["name"]): r["name"] for r in rankings}
    name = exact.get(norm(raw)) or resolve(raw, rankings)
    r = by_name.get(name)
    if r and pos and r["pos"] not in pos.split(","):
        # same name, different player (e.g. two Elias Petterssons): trust Yahoo's position
        alt = [x for x in rankings if norm(x["name"]) == norm(raw) and x["pos"] in pos.split(",")]
        r = alt[0] if alt else r
    fpg = float(r["fpg"]) if r else 0.0
    gp = float(r["proj_gp"]) if r else 0.0
    pos = pos or (r["pos"] if r else "?")
    return {
        "name": r["name"] if r else raw, "ranked": bool(r), "pos": pos,
        "group": "G" if pos == "G" else ("D" if pos == "D" else "F"),
        "status": status, "fpg": fpg, "ros": round(fpg * gp * season_left(), 1),
        "note": r["note"] if r and r.get("note") else "",
    }


def show(players):
    for p in sorted(players, key=lambda p: (p["group"], -p["ros"])):
        flag = "" if p["ranked"] else "  [unranked: judge manually]"
        st = f" {p['status']}" if p["status"] else ""
        note = f"  [{p['note']}]" if p["note"] else ""
        print(f"  {p['group']} {p['name']:24} {p['pos']:8}{st:7} FP/G {p['fpg']:5.2f}  ROS {p['ros']:6.1f}{flag}{note}")


def week_adds(state, today=None):
    today = today or date.today()
    monday = today - timedelta(days=today.weekday())
    return [a for a in state["adds"] if date.fromisoformat(a["date"]) >= monday]


def cmd_eval(specs, rankings, state):
    mine = [parse(f"{r['name']}|{r['pos']}|{r['status']}", rankings) for r in state["roster"]]
    if not mine:
        sys.exit("roster is empty: run `manage.py roster set ...` first")
    fas = [parse(s, rankings) for s in specs]
    used = len(week_adds(state))
    auto_left = max(0, min(RULES["max_auto_adds_per_week"], RULES["league_max_adds_per_week"]) - used)
    protected = set(RULES["protected"])
    healthy_g = [p for p in mine if p["group"] == "G" and p["status"] not in INJURED]
    print(f"Season left {season_left():.0%} | adds this week {used}/{RULES['league_max_adds_per_week']} "
          f"(auto budget left {auto_left}) | healthy G {len(healthy_g)}")
    moves = []
    for fa in fas:
        if fa["status"] in INJURED:
            continue
        # drop candidates: same group (so G swaps only with G and the goalie count holds), not protected
        cands = [p for p in mine if p["group"] == fa["group"] and p["name"] not in protected]
        for d in cands:
            gain = fa["ros"] - d["ros"]
            if gain <= 0:
                continue
            auto = (fa["ranked"] and gain >= RULES["min_ros_gain_fp"] and auto_left > 0
                    and (fa["group"] != "G" or RULES.get("auto_goalie_swaps", False)))
            moves.append((gain, fa, d, auto))
    moves.sort(key=lambda m: -m[0])
    seen_fa, seen_drop = set(), set()
    print("\nBest swaps (one per FA and per drop):")
    for gain, fa, d, auto in moves:
        if fa["name"] in seen_fa or d["name"] in seen_drop:
            continue
        seen_fa.add(fa["name"]); seen_drop.add(d["name"])
        tag = "AUTO-OK" if auto else "ASK"
        print(f"  [{tag}] add {fa['name']} ({fa['pos']}, ROS {fa['ros']:.0f}) / drop {d['name']} ({d['pos']}, ROS {d['ros']:.0f})  +{gain:.0f} FP")
    if not seen_fa:
        print("  none: no free agent beats a droppable player")
    unranked = [f["name"] for f in fas if not f["ranked"]]
    if unranked:
        print("\nUnranked FAs (no model value, judge manually / ask owner):", ", ".join(unranked))


def main():
    rankings = load_rankings()
    state = load_state()
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("roster", [])
    if cmd == "roster":
        if args[:1] == ["set"]:
            players = [parse(s, rankings) for s in args[1:]]
            state["roster"] = [{"name": p["name"], "pos": p["pos"], "status": p["status"]} for p in players]
            save_state(state)
            print(f"roster saved ({len(players)} players)")
        show([parse(f"{r['name']}|{r['pos']}|{r['status']}", rankings) for r in state["roster"]])
    elif cmd == "eval":
        cmd_eval(args, rankings, state)
    elif cmd == "acq":
        auto = "--auto" in args
        add, drop = [a for a in args if a != "--auto"][:2]
        state["adds"].append({"date": date.today().isoformat(), "add": add, "drop": drop, "auto": auto})
        save_state(state)
        print(f"recorded: +{add} / -{drop}{' (auto)' if auto else ''}; this week {len(week_adds(state))}")
    elif cmd == "week":
        adds = week_adds(state)
        print(f"{len(adds)}/{RULES['league_max_adds_per_week']} this week")
        for a in adds:
            print(f"  {a['date']} +{a['add']} / -{a['drop']}{' (auto)' if a['auto'] else ''}")
    elif cmd == "log":
        with LOG.open("a") as f:
            f.write(scrub(f"- {datetime.now():%Y-%m-%d %H:%M} {' '.join(args)}\n"))
        print("logged")
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
