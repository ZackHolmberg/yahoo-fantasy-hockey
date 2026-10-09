"""Owner-directed add/drops ("drop Marchand, pick up the next best forward"), shared by scripts/reply_auto.py
(the owner's texts) and scripts/daily_auto.py (Monday's ESPN run makes the moves queued mid-week).

The owner asking for the move is the approval. The script, not the LLM, picks the player: the best ranked, healthy
free agent by rest-of-season value (manage.py report's PLAN_JSON "fas", best first) at the asked position, or the
dropped player's position group when none is given.
"""
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent
QUEUE = REPO / "espn/data/queued_moves.json"  # ESPN add/drops only go through on Monday before the first game
POS_GROUP = {"F": "F", "FORWARD": "F", "C": "F", "LW": "F", "RW": "F", "W": "F", "WING": "F",
             "D": "D", "DEFENSE": "D", "DEFENCE": "D", "DEFENSEMAN": "D", "G": "G", "GOALIE": "G"}


def find(name, players):
    """Match a name as the owner wrote it: exact (any case), else a unique last-name or partial match."""
    n = name.lower().strip()
    exact = [p for p in players if p["name"].lower() == n]
    if exact:
        return exact[0]
    hits = [p for p in players if n in p["name"].lower() or p["name"].lower().split()[-1] == n.split()[-1]]
    return hits[0] if len(hits) == 1 else None


def pick(plan, drop, add=None, position="", only_if_better=False, taken=()):
    """-> (drop player, add player, None), or (drop player or None, None, why not)."""
    d = find(drop, plan["roster"])
    if not d:
        return None, None, f"{drop} isn't on our roster"
    pool = [f for f in plan["fas"] if f["name"] not in taken]
    if add:
        a = find(add, pool)
        if not a:
            return d, None, f"{add} isn't among the ranked, healthy free agents I can see"
    else:
        pos = (position or "").upper().strip()
        group = POS_GROUP.get(pos, d["group"])
        cands = [f for f in pool if f["group"] == group and (pos not in ("C", "LW", "RW") or pos in f["pos"].split(","))]
        if not cands:
            return d, None, f"no ranked, healthy free agent at {pos or group}"
        a = cands[0]  # the pool is sorted best first
    if only_if_better and a["ros"] <= d["ros"]:
        return d, None, (f"the best option, {a['name']} (ROS {a['ros']:.0f}), isn't better than "
                         f"{d['name']} (ROS {d['ros']:.0f})")
    return d, a, None


def describe(d, a):
    return (f"drop {d['name']} ({d['pos']}, ROS {d['ros']:.0f}), add {a['name']} ({a['pos']}, {a['team']}, "
            f"ROS {a['ros']:.0f})")


def espn_plan():
    """ESPN report plan (reads the API; changes nothing on ESPN)."""
    r = subprocess.run([sys.executable, "manage.py", "--league", "espn", "report", "--fetch", "--json"],
                       cwd=REPO, capture_output=True, text=True, timeout=300)
    if "PLAN_JSON " not in r.stdout:
        raise RuntimeError("ESPN report failed: " + (r.stdout + r.stderr).strip()[-200:])
    return json.loads(r.stdout.split("PLAN_JSON ", 1)[1].strip().splitlines()[0])


def load_queue():
    try:
        return json.loads(QUEUE.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def save_queue(moves):
    if moves:
        QUEUE.write_text(json.dumps(moves, indent=1) + "\n")
    else:
        QUEUE.unlink(missing_ok=True)
