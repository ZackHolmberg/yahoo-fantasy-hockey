"""Yahoo API draft sync, the preferred alternative to pasting Draft Results.

    python yahoo_sync.py check          # verify auth + league access; prints settings and my team
    python yahoo_sync.py sync           # pull draft results -> data/draft_state.json, show my slot + best available
    python yahoo_sync.py eligibility    # cache Yahoo position eligibility -> data/yahoo_eligibility.json

Needs the venv (yahoo_oauth, yahoo_fantasy_api) and an authorized oauth2.json (see auth.py).
`sync` rebuilds draft state from Yahoo each time, so it's safe to run as often as you like.
If Yahoo returns 403 "not authorized", fall back to `pbpaste | python3 draft.py paste`.
"""
import difflib
import json
import logging
import re
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)

import objectpath  # noqa: E402  (dependency of yahoo_fantasy_api)
import yahoo_fantasy_api as yfa  # noqa: E402
from yahoo_oauth import OAuth2  # noqa: E402

import draft  # noqa: E402

LEAGUE_ID = "23491"
TEAMS = 12
CACHE = Path("data/yahoo_players_cache.json")
ELIG = Path("data/yahoo_eligibility.json")


def connect():
    sc = OAuth2(None, None, from_file="oauth2.json")
    gm = yfa.Game(sc, "nhl")
    league_key = f"{gm.game_id()}.l.{LEAGUE_ID}"
    return gm.to_league(league_key)


def explain(e):
    msg = str(e)
    if "not authorized" in msg:
        sys.exit("Yahoo 403 'not authorized'. The app lacks Fantasy access (see CLAUDE.md > Yahoo API).\n"
                 "Fallback: pbpaste | python3 draft.py paste")
    raise e


def cmd_check():
    try:
        lg = connect()
        s = lg.settings()
        my_key = lg.team_key()
    except RuntimeError as e:
        explain(e)
    print("League:", s.get("name"), "|", lg.league_id)
    for k in ("num_teams", "scoring_type", "draft_type", "draft_status", "draft_time", "draft_pick_time", "uses_playoff"):
        print(f"  {k}: {s.get(k)}")
    teams = lg.teams()
    print("My team:", teams.get(my_key, {}).get("name"), f"({my_key})")
    print("OK: API access works.")


def draft_slots(lg):
    """Raw draft results, including empty pre-draft slots (the library drops those)."""
    raw = lg.yhandler.get_draftresults_raw(lg.league_id)
    out = []
    for p in objectpath.Tree(raw).execute("$..draft_results..draft_result"):
        pk = p.get("player_key")
        m = re.search(r"\.p\.(\d+)$", pk or "")
        out.append(dict(pick=int(p["pick"]), round=int(p["round"]), team_key=p.get("team_key"),
                        player_id=int(m.group(1)) if m else None))
    return sorted(out, key=lambda d: d["pick"])


def names_for(lg, ids):
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    missing = [i for i in ids if str(i) not in cache]
    for i in range(0, len(missing), 25):
        for p in lg.player_details(missing[i:i + 25]):
            cache[str(p["player_id"])] = dict(
                name=p["name"]["full"],
                elig=[e["position"] for e in p.get("eligible_positions", [])
                      if e["position"] not in ("Util", "IR", "IR+", "NA", "BN", "F", "P")])
    CACHE.write_text(json.dumps(cache))
    return cache


def match(yahoo_name, by_norm):
    n = draft.norm(yahoo_name)
    if n in by_norm:
        return by_norm[n]
    close = difflib.get_close_matches(n, by_norm, n=1, cutoff=0.85)
    return by_norm[close[0]] if close else None


def cmd_sync():
    try:
        lg = connect()
        my_key = lg.team_key()
        slots = draft_slots(lg)
    except RuntimeError as e:
        explain(e)
    rankings = draft.load_rankings()
    by_norm = {draft.norm(r["name"]): r["name"] for r in rankings}

    made = [d for d in slots if d["player_id"]]
    cache = names_for(lg, [d["player_id"] for d in made])
    state, unmatched = {"taken": [], "mine": [], "unranked": []}, []
    for d in made:
        yname = cache[str(d["player_id"])]["name"]
        name = match(yname, by_norm)
        mine = d["team_key"] == my_key
        if name:
            state["mine" if mine else "taken"].append(name)
        else:
            unmatched.append(f"{yname}{' (MINE)' if mine else ''}")
    state["unranked"] = unmatched  # drafted players we can't rank still count toward pick numbers
    draft.STATE.write_text(json.dumps(state, indent=2))

    my_slot = next((d["pick"] for d in slots if d["round"] == 1 and d["team_key"] == my_key), None)
    next_pick = len(made) + 1
    print(f"Synced {len(made)} picks from Yahoo.", f"My draft slot: {my_slot}" if my_slot else "Draft order not set yet.")
    if my_slot:
        mine_upcoming = [d["pick"] for d in slots if d["team_key"] == my_key and d["pick"] >= next_pick]
        if mine_upcoming:
            print(f"Next pick overall: #{next_pick} | my next pick: #{mine_upcoming[0]} "
                  f"({'MY TURN NOW' if mine_upcoming[0] == next_pick else f'{mine_upcoming[0] - next_pick} picks away'})")
    if unmatched:
        print("Drafted but not in rankings (rookies etc.):", ", ".join(unmatched))
    print()
    draft.best(rankings, state, 15)


def cmd_eligibility():
    """Map ranked players to Yahoo eligible positions via free agents + taken players."""
    try:
        lg = connect()
        elig = {}
        for pos in ("C", "LW", "RW", "D", "G"):
            for p in lg.free_agents(pos):
                elig[p["name"]] = [e for e in p.get("eligible_positions", []) if e in ("C", "LW", "RW", "D", "G")]
        for p in lg.taken_players():
            elig[p["name"]] = [e for e in p.get("eligible_positions", []) if e in ("C", "LW", "RW", "D", "G")]
    except RuntimeError as e:
        explain(e)
    by_norm = {draft.norm(r["name"]): r["name"] for r in draft.load_rankings()}
    out = {}
    for yname, positions in elig.items():
        name = match(yname, by_norm)
        if name:
            out[name] = positions
    ELIG.write_text(json.dumps(out, indent=1, sort_keys=True))
    multi = sum(len(v) > 1 for v in out.values())
    print(f"Saved Yahoo eligibility for {len(out)} ranked players ({multi} multi-position) -> {ELIG}")


if __name__ == "__main__":
    {"check": cmd_check, "sync": cmd_sync, "eligibility": cmd_eligibility}.get(
        sys.argv[1] if len(sys.argv) > 1 else "", lambda: sys.exit(__doc__))()
