"""Live draft tracker.

    python draft.py taken "Name One" "Name Two" ...   # players drafted by others
    python draft.py mine "Name"                       # my pick
    python draft.py undo "Name"                       # remove a mistaken entry
    python draft.py best [N]                          # best available + my roster needs
    pbpaste | python draft.py paste                   # mark every player found in pasted text as taken
    python draft.py reset                             # clear state before a new draft

Stdlib only: runs with any python3, no venv needed.

Names are fuzzy-matched against data/rankings.csv. State lives in data/draft_state.json.
"""
import csv
import difflib
import json
import sys
import unicodedata
from pathlib import Path

STATE = Path("data/draft_state.json")
STARTERS = {"C": 2, "LW": 2, "RW": 2, "D": 4, "G": 1}
TARGET = {"C": 3, "LW": 3, "RW": 3, "D": 5, "G": 3}  # starters + sensible bench depth
ROSTER_SIZE = 17  # 11 active + 6 bench


def norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower().replace(".", "").strip()


def load_rankings():
    with open("data/rankings.csv") as f:
        return list(csv.DictReader(f))


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {"taken": [], "mine": []}


def resolve(name, rankings):
    by_norm = {norm(r["name"]): r["name"] for r in rankings}
    n = norm(name)
    if n in by_norm:
        return by_norm[n]
    hits = [full for key, full in by_norm.items() if n in key]
    if len(hits) == 1:
        return hits[0]
    close = difflib.get_close_matches(n, by_norm, n=1, cutoff=0.75)
    if close:
        return by_norm[close[0]]
    print(f"  ?? could not match '{name}'" + (f" (candidates: {', '.join(hits[:5])})" if hits else ""))
    return None


def load_eligibility():
    """Yahoo eligible positions from `yahoo_sync.py eligibility`, if cached."""
    path = Path("data/yahoo_eligibility.json")
    return json.loads(path.read_text()) if path.exists() else {}


def best(rankings, state, n=15):
    elig = load_eligibility()
    gone = set(state["taken"]) | set(state["mine"])
    pos_of = {r["name"]: r["pos"] for r in rankings}
    have = {p: 0 for p in STARTERS}
    for m in state["mine"]:
        have[pos_of[m]] += 1
    # only one goalie starts per day: discount 2nd/3rd goalies (backtest-neutral, avoids goalie hoarding)
    gmult = (1.0, 0.5, 0.2, 0.0)[min(have["G"], 3)]
    avail = [dict(r, vor=float(r["vor"]) * (gmult if r["pos"] == "G" else 1.0))
             for r in rankings if r["name"] not in gone]
    avail.sort(key=lambda r: -r["vor"])
    picks_made = len(state["taken"]) + len(state["mine"]) + len(state.get("unranked", []))
    print(f"Pick #{picks_made + 1} overall | my roster ({len(state['mine'])}/{ROSTER_SIZE}): "
          + ", ".join(f"{m} ({pos_of[m]})" for m in state["mine"]) if state["mine"] else f"Pick #{picks_made + 1} overall | my roster: empty")
    need = {p: max(0, STARTERS[p] - have[p]) for p in STARTERS}
    print("Unfilled starters:", {p: k for p, k in need.items() if k} or "none",
          "| have:", have)
    print(f"\nBest available overall (VOR):")
    for r in avail[:n]:
        yp = elig.get(r["name"]) or [r["pos"]]
        flag = "  <- NEED" if any(need.get(p) for p in yp) else ("" if have[r["pos"]] < TARGET[r["pos"]] else "  (deep at pos)")
        note = f"  [{r['note']}]" if r.get("note") else ""
        yahoo = f"  Yahoo:{'/'.join(yp)}" if len(yp) > 1 else ""
        print(f"  {r['rank']:>4} {r['name']:24} {r['pos_rank']:5} {r['team']:4} FP {float(r['proj_fp']):6.0f} VOR {float(r['vor']):6.1f}{flag}{yahoo}{note}")
    print("\nTop 3 by position:")
    for p in STARTERS:
        top = [r for r in avail if r["pos"] == p][:3]
        print(f"  {p:2}: " + " | ".join(f"{r['name']} ({float(r['vor']):.0f})" for r in top))


def main():
    rankings = load_rankings()
    state = load_state()
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("best", [])
    if cmd in ("taken", "mine", "undo"):
        for a in args:
            name = resolve(a, rankings)
            if not name:
                continue
            if cmd == "undo":
                for k in ("taken", "mine"):
                    if name in state[k]:
                        state[k].remove(name)
                print(f"  undone: {name}")
            elif name in state["taken"] or name in state["mine"]:
                print(f"  already recorded: {name}")
            else:
                state[cmd].append(name)
                print(f"  {cmd}: {name}")
        STATE.write_text(json.dumps(state, indent=2))
        print()
        best(rankings, state, 10)
    elif cmd == "paste":
        # Yahoo draft-results text in any layout: match every known player name that appears in it.
        text = norm(sys.stdin.read())
        mine = set(state["mine"])
        found = [r["name"] for r in rankings if norm(r["name"]) in text]
        new = [n for n in found if n not in mine and n not in state["taken"]]
        state["taken"] += new
        STATE.write_text(json.dumps(state, indent=2))
        print(f"  matched {len(found)} players in paste, {len(new)} newly marked taken")
        if mine & set(found):
            print("  (skipped my own players:", ", ".join(sorted(mine & set(found))) + ")")
        print("  NOTE: rookies/players without NHL history aren't in rankings and are ignored.")
        print()
        best(rankings, state, 10)
    elif cmd == "reset":
        STATE.unlink(missing_ok=True)
        print("state cleared")
    else:
        best(rankings, state, int(args[0]) if args else 15)


if __name__ == "__main__":
    main()
