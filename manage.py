"""In-season team manager (companion to docs/MANAGER.md).

    python3 manage.py roster set "Name|POS|STATUS" ...   # replace my roster (POS as Yahoo shows it, e.g. LW,RW; STATUS e.g. IR, DTD, O or empty)
    python3 manage.py roster                             # show roster with rest-of-season value
    python3 manage.py eval "Name|POS|STATUS" ...         # rank free agents against my droppable players
    python3 manage.py acq "Add Name" "Drop Name" [--auto] # record a completed add/drop
    python3 manage.py week                               # acquisitions used this week (Mon-Sun)
    python3 manage.py log "text"                         # append a line to data/season_log.md
    python3 manage.py lineup [YYYY-MM-DD]                # ESPN: best weekly lineup for the week containing that date
    python3 manage.py --league espn report --fetch       # ESPN without Chrome: reads the API with espn/data/espn_auth.json
    python3 manage.py trade --give "A;B" --get "C" --theirs "<spec> ~ <spec> ..."   # both sides' lineup-value change
    python3 manage.py trade-ideas --team N "<spec> ~ ..." [--team M ...]          # 1-for-1 trades good for both sides
    (ESPN: --theirs/--team rosters can be omitted; they're read from the API.)
    python3 manage.py report '<chunk>' ...               # daily report: syncs the roster, prints ACTIONS / ASK / text draft.
                                                         # payload chunks come from scripts/yahoo_read.js or espn_read.js.

    --league espn (first argument) runs against ESPN league 1034056432: state, rules and rankings in espn/data/.

Stdlib only. Values come from data/rankings.csv (preseason model); unranked players get no value
and are never auto-added. Guardrails live in data/manager_rules.json.
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

if sys.argv[1:2] == ["--league"]:  # must run before the draft import: draft.py reads LEAGUE at import
    os.environ["LEAGUE"] = sys.argv[2]
    os.chdir(Path(__file__).resolve().parent / sys.argv[2])
    del sys.argv[1:3]
ESPN = os.environ.get("LEAGUE") == "espn"

from draft import load_rankings, norm, resolve
from team_alias import scrub

STATE = Path("data/season_state.json")
RULES = json.loads(Path("data/manager_rules.json").read_text())
LOG = Path("data/season_log.md")
INJURED = {"IR", "IR-LT", "IR-NR", "O", "OUT", "INJ", "INJURY_RESERVE", "SUSPENSION"}
# ESPN team abbreviations that differ from the NHL API's
NHL_ABBR = {"TB": "TBL", "NJ": "NJD", "SJ": "SJS", "LA": "LAK", "WAS": "WSH", "MON": "MTL", "UTAH": "UTA"}


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
    parts = [p.strip() for p in spec.split("|")] + ["", "", ""]
    raw, pos, status, team = parts[0].replace("\u2019", "'"), parts[1].upper(), parts[2].upper(), parts[3].upper()
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
        "team": NHL_ABBR.get(team, team) or (r["team"] if r else ""), "gp": gp,
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


def my_players(state, rankings):
    return [parse(f"{r['name']}|{r['pos']}|{r['status']}|{r.get('team', '')}", rankings) for r in state["roster"]]


def swaps(mine, fas, state):
    """Best add/drop swaps, one per FA and per drop: [(tag, gain, fa, drop)]. AUTO-OK capped by the weekly budget."""
    used = len(week_adds(state))
    auto_left = max(0, min(RULES["max_auto_adds_per_week"], RULES["league_max_adds_per_week"]) - used)
    protected = set(RULES["protected"])
    # claims/moves from the last 7 days may still be pending on the site: never suggest them twice
    recent = [a for a in state["adds"] if date.fromisoformat(a["date"]) >= date.today() - timedelta(days=7)]
    pending = {a["add"] for a in recent} | {a["drop"] for a in recent}
    moves = []
    for fa in fas:
        if fa["status"] in INJURED or fa["name"] in pending:
            continue
        # drop candidates: same group (so G swaps only with G and the goalie count holds), not protected
        cands = [p for p in mine if p["group"] == fa["group"] and p["name"] not in protected | pending]
        for d in cands:
            gain = fa["ros"] - d["ros"]
            if gain <= 0:
                continue
            auto = (fa["ranked"] and gain >= RULES["min_ros_gain_fp"]
                    and (fa["group"] != "G" or RULES.get("auto_goalie_swaps", False)))
            moves.append((gain, fa, d, auto))
    moves.sort(key=lambda m: -m[0])
    out, seen_fa, seen_drop = [], set(), set()
    for gain, fa, d, auto in moves:
        if fa["name"] in seen_fa or d["name"] in seen_drop:
            continue
        seen_fa.add(fa["name"]); seen_drop.add(d["name"])
        ok = auto and auto_left > 0
        auto_left -= ok
        out.append(("AUTO-OK" if ok else "ASK", gain, fa, d))
    return out, used


def cmd_eval(specs, rankings, state):
    mine = my_players(state, rankings)
    if not mine:
        sys.exit("roster is empty: run `manage.py roster set ...` first")
    fas = [parse(s, rankings) for s in specs]
    found, used = swaps(mine, fas, state)
    healthy_g = [p for p in mine if p["group"] == "G" and p["status"] not in INJURED]
    print(f"Season left {season_left():.0%} | adds this week {used}/{RULES['league_max_adds_per_week']} "
          f"(auto max {RULES['max_auto_adds_per_week']}) | healthy G {len(healthy_g)}")
    print("\nBest swaps (one per FA and per drop):")
    for tag, gain, fa, d in found:
        print(f"  [{tag}] add {fa['name']} ({fa['pos']}, ROS {fa['ros']:.0f}) / drop {d['name']} ({d['pos']}, ROS {d['ros']:.0f})  +{gain:.0f} FP")
    if not found:
        print("  none: no free agent beats a droppable player")
    unranked = [f["name"] for f in fas if not f["ranked"]]
    if unranked:
        print("\nUnranked FAs (no model value, judge manually / ask owner):", ", ".join(unranked))


def week_games(day):
    """NHL games per team in the Mon-Sun week containing `day` (NHL schedule API)."""
    monday = day - timedelta(days=day.weekday())
    url = f"https://api-web.nhle.com/v1/schedule/{monday.isoformat()}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})  # the API 403s urllib's default UA
    with urllib.request.urlopen(req, timeout=20) as r:
        weeks = json.load(r)["gameWeek"]
    games = {}
    for d in weeks:
        if not (monday <= date.fromisoformat(d["date"]) <= monday + timedelta(days=6)):
            continue
        for g in d["games"]:
            for side in ("homeTeam", "awayTeam"):
                games[g[side]["abbrev"]] = games.get(g[side]["abbrev"], 0) + 1
    return monday, games


def espn_week_plan(mine, day):
    """ESPN weekly lineup: 12 F, 6 D, 2 G by projected points for the week containing `day`."""
    monday, games = week_games(day)
    benched = set(RULES.get("do_not_start", []))
    for p in mine:
        g = games.get(p["team"], 0)
        if p["status"] in INJURED or p["name"] in benched:
            g = 0
        elif p["status"] in {"DTD", "DAY_TO_DAY"}:
            g *= 0.7
        share = min(1.0, p["gp"] / 82) if p["group"] == "G" else 1.0  # goalies: share of team starts
        p["games"], p["week"] = games.get(p["team"], 0), round(p["fpg"] * g * share, 1)
    start = []
    for grp, n in ESPN_SLOTS.items():
        start += sorted((p for p in mine if p["group"] == grp), key=lambda p: -p["week"])[:n]
    bench = [p for p in mine if p not in start]
    ir = [p for p in bench if p["status"] in INJURED][:2]
    return monday, start, ir, [p for p in bench if p not in ir]


def cmd_lineup(args, rankings, state):
    day = date.fromisoformat(args[0]) if args else date.today()
    mine = my_players(state, rankings)
    monday, start, ir, bench = espn_week_plan(mine, day)
    slots = ESPN_SLOTS
    print(f"Week of {monday} (lineup locks at the week's first game)")
    for grp in slots:
        print(f"\n{grp} starters:")
        for p in sorted((p for p in start if p["group"] == grp), key=lambda p: -p["week"]):
            print(f"  {p['name']:24} {p['team']:4} games {p['games']}  proj {p['week']:5.1f}{'  ' + p['status'] if p['status'] else ''}")
    print("\nIR slots (max 2):", ", ".join(p["name"] for p in ir) or "none")
    print("Bench:", ", ".join(f"{p['name']} ({p['week']:.1f})" for p in bench) or "none")
    unranked = [p["name"] for p in mine if not p["ranked"]]
    if unranked:
        print("Unranked (projected 0, judge manually):", ", ".join(unranked))


ESPN_SLOTS = {"F": 12, "D": 6, "G": 2}
YAHOO_SLOTS = ["C", "C", "LW", "LW", "RW", "RW", "D", "D", "D", "D"]  # plus one G; no Util
ACTIVE = {"C", "LW", "RW", "D", "G", "F", "UTIL"}
IR_SLOTS = {"IR", "IR+", "NA"}


def day_teams(day):
    """Teams with an NHL game on `day`."""
    url =f"https://api-web.nhle.com/v1/schedule/{day.isoformat()}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=20) as r:
        week = json.load(r)["gameWeek"]
    return {g[s]["abbrev"] for d in week if d["date"] == day.isoformat() for g in d["games"] for s in ("homeTeam", "awayTeam")}


def goalie_status(day):
    """{goalie name: 'Confirmed'|'Likely'|''} for `day` from DailyFaceoff's starting-goalies page; {} if unreachable."""
    url = f"https://www.dailyfaceoff.com/starting-goalies/{day.isoformat()}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                                               "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0 Safari/537.36"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "ignore")
        data = json.loads(re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S).group(1))
        out = {}
        for g in data["props"]["pageProps"]["data"]:
            for side in ("away", "home"):
                if g.get(f"{side}GoalieName"):
                    out[g[f"{side}GoalieName"]] = g.get(f"{side}NewsStrengthName") or ""
        return out
    except Exception:
        return {}


def yahoo_day_plan(mine, playing, current=None, starters=None):
    """Best skater lineup for one day: greedy by FP/G with a bipartite feasibility check (optimal here,
    because a player's value doesn't depend on the slot). Goalie: best FP/G x start share among those playing."""
    def value(p):
        if p["status"] in INJURED or p["team"] not in playing or p["name"] in RULES.get("do_not_start", []):
            return 0
        return p["fpg"] * (0.7 if p["status"] in {"DTD", "DAY_TO_DAY"} else 1)
    sk = sorted((p for p in mine if p["group"] != "G" and value(p) > 0), key=lambda p: -value(p))
    owner = {}  # slot index -> player

    current = current or {}

    def fits(p, seen):
        # try the player's current slot first so a valid lineup isn't reshuffled for nothing
        order = sorted(range(len(YAHOO_SLOTS)), key=lambda i: YAHOO_SLOTS[i] != current.get(p["name"]))
        for i in order:
            slot = YAHOO_SLOTS[i]
            if slot in p["pos"].split(",") and i not in seen:
                seen.add(i)
                if i not in owner or fits(owner[i], seen):
                    owner[i] = p
                    return True
        return False
    for p in sk:
        snapshot = dict(owner)
        if not fits(p, set()):
            owner.clear(); owner.update(snapshot)
    plan = {p["name"]: YAHOO_SLOTS[i] for i, p in owner.items()}
    # chance he actually starts: DailyFaceoff's status when known, else his share of team starts
    starters = starters or {}
    by_norm = {norm(n): st for n, st in starters.items()}

    def start_odds(p):
        st = by_norm.get(norm(p["name"]))
        if st is None:
            return min(1.0, p["gp"] / 82) * (0.5 if starters else 1.0)  # not projected to start today
        return {"Confirmed": 1.0, "Likely": 0.8}.get(st, 0.6)
    goalies = sorted((p for p in mine if p["group"] == "G" and value(p) > 0), key=lambda p: -value(p) * start_odds(p))
    for g in goalies:
        g["start"] = by_norm.get(norm(g["name"]))
    if goalies:
        plan[goalies[0]["name"]] = "G"
    return plan, goalies


ESPN_API = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fhl/seasons/2027"
ESPN_LEAGUE, ESPN_TEAM = 1034056432, 5
ESPN_POS = {1: "F", 2: "F", 3: "F", 4: "D", 5: "G"}
ESPN_SLOT = {3: "F", 4: "D", 5: "G", 7: "BE", 8: "IR"}


def espn_fetch(team=None, all_teams=False):
    """Same payload as scripts/espn_read.js, read straight from ESPN's API with the owner's cookies.
    team=N returns that team's roster specs; all_teams=True returns {team id: [spec, ...]} for every team."""
    auth = json.loads(Path("data/espn_auth.json").read_text())
    if not auth.get("espn_s2") or not auth.get("SWID"):
        sys.exit("espn_fetch: fill espn_s2 and SWID in espn/data/espn_auth.json (see its _comment), or use the Chrome snippet")
    cookie = f"espn_s2={auth['espn_s2']}; SWID={auth['SWID']}"

    def get(url, fantasy_filter=None):
        headers = {"User-Agent": "Mozilla/5.0", "Cookie": cookie}
        if fantasy_filter:
            headers["x-fantasy-filter"] = json.dumps(fantasy_filter)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                sys.exit(f"espn_fetch: ESPN refused the cookies (HTTP {e.code}). They may have expired: "
                         "re-copy espn_s2 and SWID into espn/data/espn_auth.json")
            raise
    league_url = f"{ESPN_API}/segments/0/leagues/{ESPN_LEAGUE}"
    teams = {t["id"]: t["abbrev"].upper() for t in get(f"{ESPN_API}?view=proTeamSchedules_wl")["settings"]["proTeams"]}

    def fmt(pl):
        st = pl.get("injuryStatus") or ""
        return f"{pl['fullName']}|{ESPN_POS.get(pl['defaultPositionId'], '?')}|{'' if st == 'ACTIVE' else st}|{teams.get(pl['proTeamId'], '')}"
    league = get(f"{league_url}?view=mRoster")
    if team is not None or all_teams:
        rosters = {t["id"]: [fmt(e["playerPoolEntry"]["player"]) for e in t["roster"]["entries"]] for t in league["teams"]}
        return rosters if all_teams else rosters[team]
    mine = next(t for t in league["teams"] if t["id"] == ESPN_TEAM)
    items = [f"D {date.today().isoformat()}"]
    items += [f"R {ESPN_SLOT.get(e['lineupSlotId'], e['lineupSlotId'])}:{fmt(e['playerPoolEntry']['player'])}"
              for e in mine["roster"]["entries"]]
    fa = get(f"{league_url}?view=kona_player_info", {"players": {
        "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]}, "limit": 40,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False}}})
    items += [f"F {fmt(x['player'])}" for x in fa["players"]]
    return " ~ ".join(items)


REPL_CACHE = {}


def replacement_ros(pos):
    """Rest-of-season FP of a waiver-level player at a position (the VOR baseline): what fills an empty slot."""
    if pos not in REPL_CACHE:
        rows = [r for r in load_rankings() if r["pos"] == pos]
        REPL_CACHE[pos] = (float(rows[0]["proj_fp"]) - float(rows[0]["vor"])) * season_left() if rows else 0.0
    return REPL_CACHE[pos]


def lineup_value(players):
    """Rest-of-season FP of the best starting lineup this roster can field. Empty slots count as a waiver pickup
    (replacement level), since a real team would fill them; the bench adds nothing."""
    healthy = [p for p in players if p["status"] not in INJURED]
    if ESPN:
        total = 0.0
        for g, n in ESPN_SLOTS.items():
            vals = sorted((p["ros"] for p in healthy if p["group"] == g), reverse=True)[:n]
            vals += [replacement_ros(g)] * (n - len(vals))
            total += sum(max(v, replacement_ros(g)) for v in vals)
        return total
    owner = {}

    def fits(p, seen):
        for i, slot in enumerate(YAHOO_SLOTS):
            if slot in p["pos"].split(",") and i not in seen:
                seen.add(i)
                if i not in owner or fits(owner[i], seen):
                    owner[i] = p
                    return True
        return False
    for p in sorted((p for p in healthy if p["group"] != "G"), key=lambda p: -p["ros"]):
        snap = dict(owner)
        if not fits(p, set()):
            owner.clear(); owner.update(snap)
    goalies = sorted((p["ros"] for p in healthy if p["group"] == "G"), reverse=True) + [replacement_ros("G")] * 2
    filled = sum(max(p["ros"], replacement_ros(YAHOO_SLOTS[i])) for i, p in owner.items())
    empty = sum(replacement_ros(YAHOO_SLOTS[i]) for i in range(len(YAHOO_SLOTS)) if i not in owner)
    # one G slot: the #1 counts fully, the #2 covers the #1's nights off (same discount as the draft tracker)
    return filled + empty + goalies[0] + 0.5 * goalies[1]


def trade_eval(mine, theirs, give, get):
    """Both sides' change in best-lineup ROS FP. give/get: player names (fuzzy-matched within the two rosters)."""
    def pick(names, roster):
        out = []
        for n in names:
            m = [p for p in roster if norm(p["name"]) == norm(n)] or [p for p in roster if norm(n) in norm(p["name"])]
            if len(m) != 1:
                raise ValueError(f"can't find exactly one '{n}' on that roster")
            out.append(m[0])
        return out
    g, r = pick(give, mine), pick(get, theirs)
    us_after = [p for p in mine if p not in g] + r
    them_after = [p for p in theirs if p not in r] + g
    us = round(lineup_value(us_after) - lineup_value(mine), 1)
    them = round(lineup_value(them_after) - lineup_value(theirs), 1)
    verdict = ("good for both sides: worth offering" if us > 0 and them > 0 else
               "good for us, but they lose value: they'd likely refuse" if us > 0 else
               "bad for us: don't offer" if them > 0 else "bad for both sides")
    return {"give": [(p["name"], p["pos"], round(p["ros"])) for p in g],
            "get": [(p["name"], p["pos"], round(p["ros"])) for p in r],
            "us": us, "them": them, "verdict": verdict}


def cmd_trade(args, rankings, state):
    def opt(name):
        return [a for i, a in enumerate(args) if i and args[i - 1] == name]
    give = [x for v in opt("--give") for x in v.split(";") if x.strip()]
    get = [x for v in opt("--get") for x in v.split(";") if x.strip()]
    mine = my_players(state, rankings)
    if opt("--theirs"):
        theirs = [parse(x, rankings) for x in " ~ ".join(opt("--theirs")).split("~") if x.strip()]
    elif ESPN and opt("--team"):
        theirs = [parse(x, rankings) for x in espn_fetch(team=int(opt("--team")[0]))]
    else:
        sys.exit("trade: pass --theirs '<spec> ~ ...' (or --team N on ESPN)")
    print(json.dumps(trade_eval(mine, theirs, give, get)))


def cmd_trade_ideas(args, rankings, state):
    """1-for-1 trades where both sides' best lineup improves, best first (by the smaller side's gain)."""
    mine = my_players(state, rankings)
    teams = {}
    for i, a in enumerate(args):
        if a == "--team":
            tid = args[i + 1]
            nxt = args[i + 2] if i + 2 < len(args) and not args[i + 2].startswith("--") else ""
            teams[tid] = [parse(x, rankings) for x in nxt.split("~") if x.strip()] if nxt else \
                [parse(x, rankings) for x in espn_fetch(team=int(tid))]
    if ESPN and not teams:
        teams = {str(t): [parse(x, rankings) for x in specs] for t, specs in espn_fetch(all_teams=True).items() if t != ESPN_TEAM}
    protected = set(RULES["protected"])
    ideas = []
    for tid, theirs in teams.items():
        for a in mine:
            if a["status"] in INJURED or not a["ranked"]:
                continue
            for b in theirs:
                if b["status"] in INJURED or not b["ranked"] or abs(a["ros"] - b["ros"]) > 60:
                    continue
                t = trade_eval(mine, theirs, [a["name"]], [b["name"]])
                if t["us"] > 0 and t["them"] > 0:
                    ideas.append({"team": tid, **t, "protected_give": a["name"] in protected})
    ideas.sort(key=lambda t: -min(t["us"], t["them"]))
    seen, out = set(), []
    for t in ideas:  # at most one idea per player we'd give
        if t["give"][0][0] not in seen:
            seen.add(t["give"][0][0]); out.append(t)
    print(json.dumps(out[:5]))


def next_question_number(prefix):
    text = LOG.read_text() if LOG.exists() else ""
    nums = [int(n) for n in re.findall(rf"\b{prefix}(\d+)\b", text)]
    return max(nums, default=0) + 1


def cmd_report(args, rankings, state):
    """Sync the roster from a read snippet's JSON, then print exactly what to do. Read-only apart from the sync."""
    want_json = "--json" in args
    args = [a for a in args if a != "--json"]
    if args[:1] == ["--fetch"]:
        if not ESPN:
            sys.exit("report --fetch is ESPN-only (Yahoo's API is blocked; use scripts/yahoo_read.js)")
        raw = espn_fetch()
    else:
        raw = sys.stdin.read() if args[:1] == ["-"] else "".join(args)  # chunks from the read snippet, in order
    data = {"date": "", "roster": [], "freeAgents": []}
    for item in filter(None, (x.strip() for x in raw.split("~"))):
        key, _, val = item.partition(" ")
        if key == "D":
            data["date"] = val
        elif key == "R":
            slot, _, spec = val.partition(":")
            data["roster"].append({"slot": slot, "spec": spec})
        elif key == "F":
            data["freeAgents"].append(val)
    if not data["roster"]:
        sys.exit("report: no roster in the payload (pass every chunk, in order)")
    today = date.fromisoformat(data["date"] or date.today().isoformat())
    league = "ESPN" if ESPN else "Yahoo"
    slot_of = {}
    specs = []
    for r in data["roster"]:
        p = parse(r["spec"], rankings)
        slot_of[p["name"]] = r["slot"].upper()
        specs.append(p)
    state["roster"] = [{"name": p["name"], "pos": p["pos"], "status": p["status"], "team": p["team"]} for p in specs]
    save_state(state)
    mine = my_players(state, rankings)
    fas = [parse(s.replace(" (waivers)", ""), rankings) for s in data.get("freeAgents", [])]
    actions, ask, fyi = [], [], []
    # machine-readable twin of ACTIONS for scripts that apply them (yahoo_bot.py): `report --json ...`
    plan_json = {"league": league.lower(), "date": today.isoformat(), "lineup": {}, "ir": [], "swaps": [], "ask": []}
    # for owner-directed moves ("drop X, add the best D"): our roster and the ranked, healthy FA pool, best first
    brief = lambda p: {k: p[k] for k in ("name", "pos", "group", "status", "ros", "team")}
    plan_json["roster"] = [brief(p) for p in mine]
    plan_json["fas"] = [brief(f) for f in sorted(fas, key=lambda f: -f["ros"])
                        if f["ranked"] and f["status"] not in INJURED][:60]

    # injuries: injured players out of IR slots, healthy players stuck in IR slots
    n_ir = sum(1 for v in slot_of.values() if v in IR_SLOTS)
    ir_cap = 2 if ESPN else 3
    for p in mine:
        slot = slot_of.get(p["name"], "")
        if p["status"] in INJURED and slot not in IR_SLOTS:
            if n_ir < ir_cap:
                actions.append(f"IR: move {p['name']} ({p['status']}) from {slot} to an IR slot")
                plan_json["ir"].append(p["name"])
                n_ir += 1
            else:
                ask.append(f"{p['name']} is {p['status']} but all IR slots are full")
        elif slot in IR_SLOTS and p["status"] not in INJURED and slot != "NA":
            ask.append(f"{p['name']} is healthy ({p['status'] or 'active'}) but in {slot}: activating needs a roster spot (drop someone?)")

    # lineup
    if ESPN:
        if today.weekday() in (6, 0):  # Sunday: next week's lineup; Monday: this week's, before the lock
            target_day = today + timedelta(days=1) if today.weekday() == 6 else today
            monday, start, ir, bench = espn_week_plan(mine, target_day)
            want = {p["name"]: p["group"] for p in start}
            for p in sorted(mine, key=lambda p: p["group"]):
                cur, new = slot_of.get(p["name"], ""), want.get(p["name"], "BE")
                if p in ir:
                    continue  # handled above
                if (cur in ACTIVE) != (new != "BE"):
                    plan_json["lineup"][p["name"]] = new
                    actions.append(f"LINEUP (week of {monday}): {'start' if new != 'BE' else 'bench'} {p['name']} "
                                   f"({p['group']}, {p['games']} games, proj {p['week']:.1f}); now {cur}")
        else:
            fyi.append("ESPN lineup is locked mid-week; next lineup run is Sunday 21:00")
    else:
        playing = day_teams(today)
        plan, goalies = yahoo_day_plan(mine, playing, slot_of, goalie_status(today))
        # Only moves that change who plays: a playing player who should start but sits, or sits in a slot the
        # plan needs for someone else. Players without a game can stay wherever they are.
        by_name = {p["name"]: p for p in mine}
        for name, new in sorted(plan.items(), key=lambda kv: kv[1]):
            cur = slot_of.get(name, "")
            if cur == new:
                continue
            p = by_name[name]
            out = [o for o, s in slot_of.items() if s == new and o not in plan and o in by_name]
            # the occupant to move out: someone in that slot type who isn't in today's plan
            vacate = f"; move {out[0]} to BN" if out and cur in ("BN", "") else ""
            plan_json["lineup"][name] = new
            if vacate:
                plan_json["lineup"].setdefault(out[0], "BN")
            actions.append(f"LINEUP {today}: {name} ({p['pos']}, {p['team']}, FP/G {p['fpg']:.2f}) {cur} -> {new}{vacate}")
        if goalies:
            st = lambda g: {None: "not listed as today's starter", "": "listed, unconfirmed"}.get(g["start"]) or g["start"].lower()
            fyi.append(f"Goalie: {goalies[0]['name']} ({st(goalies[0])} on DailyFaceoff)"
                       + ("; others playing: " + ", ".join(f"{g['name']} ({st(g)})" for g in goalies[1:]) if goalies[1:] else ""))
        else:
            fyi.append("No goalie of ours plays today")

    # free agents
    found, used = swaps(mine, fas, state)
    # ESPN only accepts add/drops on Monday before the week's first game (HTTP 409 any other day):
    # hold them, auto and ask alike, so Monday's run makes or raises them
    hold = ESPN and today.weekday() != 0
    for tag, gain, fa, d in found:
        line = f"add {fa['name']} ({fa['pos']}, {fa['team']}, ROS {fa['ros']:.0f}) / drop {d['name']} ({d['pos']}, ROS {d['ros']:.0f}) +{gain:.0f}"
        if hold:
            if tag == "AUTO-OK" or gain >= RULES["min_ros_gain_fp"]:
                plan_json.setdefault("held", []).append(f"[{tag}] {line}")
                fyi.append(f"Held for Monday (ESPN add/drops are Monday-only): [{tag}] {line}")
            continue
        if tag == "AUTO-OK" or gain >= RULES["min_ros_gain_fp"]:
            plan_json["swaps" if tag == "AUTO-OK" else "ask"].append(
                {"add": fa["name"], "drop": d["name"], "gain": round(gain), "add_pos": fa["pos"], "add_team": fa["team"]})
        if tag == "AUTO-OK":
            actions.append(f"ADD/DROP [AUTO-OK]: {line}; then `manage.py{' --league espn' if ESPN else ''} acq \"{fa['name']}\" \"{d['name']}\" --auto`")
        elif gain >= RULES["min_ros_gain_fp"]:
            ask.append(f"[ASK] {line}")
    small = sum(1 for t, g, *_ in found if t == "ASK" and g < RULES["min_ros_gain_fp"])
    if small:
        fyi.append(f"{small} more swap(s) under +{RULES['min_ros_gain_fp']} ROS: not worth raising")
    unranked = [f["name"] for f in fas if not f["ranked"]]
    if unranked:
        fyi.append("Unranked FAs (model can't value; mention only with news): " + ", ".join(unranked[:8]))
    fyi.append(f"Adds this week {used}/{RULES['league_max_adds_per_week']}")

    print(f"== {league} report {today:%a %Y-%m-%d} | roster {len(mine)} synced ==")
    print("\nACTIONS (do these, verify each on the page, then re-run read + report: this list should be empty):")
    print("\n".join(f"  {i}. {a}" for i, a in enumerate(actions, 1)) or "  none")
    prefix = "E" if ESPN else "Q"
    n = next_question_number(prefix)
    print(f"\nASK OWNER (number them {prefix}{n}, {prefix}{n + 1}, ...; log and text):")
    print("\n".join(f"  - {a}" for a in ask) or "  none")
    print("\nFYI:")
    print("\n".join(f"  - {a}" for a in fyi))
    tag = "ESPN: " if ESPN else ""
    if actions or ask:
        moves = [a.split(": ", 1)[1].split("; then")[0] for a in actions if not a.startswith("LINEUP")]
        lineup = sum(1 for a in actions if a.startswith("LINEUP"))
        parts = ([f"lineup set ({lineup} change{'s' * (lineup != 1)})"] if lineup else []) + moves
        parts += [f"{prefix}{n + i}: {q.replace('[ASK] ', '')}?" for i, q in enumerate(ask)]
        print(f"\nTEXT DRAFT (edit to what actually happened): {tag}" + "; ".join(parts))
    else:
        print("\nTEXT DRAFT (quiet day): check done, no actions needed.")
    if want_json:
        plan_json["ask_text"] = ask
        plan_json["question_prefix"], plan_json["next_question"] = prefix, n
        print("\nPLAN_JSON " + json.dumps(plan_json))


def main():
    rankings = load_rankings()
    state = load_state()
    cmd, args = (sys.argv[1], sys.argv[2:]) if len(sys.argv) > 1 else ("roster", [])
    if cmd == "roster":
        if args[:1] == ["set"]:
            players = [parse(s, rankings) for s in args[1:]]
            state["roster"] = [{"name": p["name"], "pos": p["pos"], "status": p["status"], "team": p["team"]} for p in players]
            save_state(state)
            print(f"roster saved ({len(players)} players)")
        show([parse(f"{r['name']}|{r['pos']}|{r['status']}|{r.get('team', '')}", rankings) for r in state["roster"]])
    elif cmd == "report":
        cmd_report(args, rankings, state)
    elif cmd == "trade":
        cmd_trade(args, rankings, state)
    elif cmd == "trade-ideas":
        cmd_trade_ideas(args, rankings, state)
    elif cmd == "lineup":
        cmd_lineup(args, rankings, state)
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
