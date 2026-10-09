#!/usr/bin/python3
"""Handle the owner's iMessage reply without a Claude agent. Usage: scripts/reply_auto.py "<owner's text>"

1. Context: open questions (Q.. Yahoo / E.. ESPN) parsed from the season logs, both rosters, recent log lines.
2. Understand: the LLM layer (llm.py; driver in data/llm.json) turns the free-form text into one intent as JSON.
3. Check: the script validates it (the question exists and is open, players are on the right rosters, the league
   is known). Anything that doesn't check out gets a clarifying text, never a guess.
4. Act: approved add/drops and owner-directed moves ("drop X, add the best D", moves.py picks the player) run
   through yahoo_bot.py / espn_bot.py swap (ESPN mid-week: queued for Monday); trade questions run manage.py trade /
   trade-ideas. Trades are never sent (owner-only), so the reply includes a ready-to-paste note.
5. Reply: the LLM phrases the answer from what the scripts found; logged in the league's season log.
"""
import contextlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import llm  # noqa: E402
import moves  # noqa: E402
import team_alias  # noqa: E402

LOGS = {"yahoo": REPO / "data/season_log.md", "espn": REPO / "espn/data/season_log.md"}
STATES = {"yahoo": REPO / "data/season_state.json", "espn": REPO / "espn/data/season_state.json"}
DRY = bool(os.environ.get("REPLY_DRY"))  # test mode: no texts, no log lines, bot swaps as --dry-run
Q_RE = re.compile(r"\b([QE]\d+): add (.+?) \(([^)]*)\), drop (.+?)\?")
DONE_RE = re.compile(r"\bResolved ([QE]\d+)\b")

SYSTEM = """You read text messages from the owner of two fantasy hockey teams (a Yahoo league and an ESPN league)
and output what they want as JSON. You never decide moves yourself. Output exactly these keys:
{"league": "yahoo"|"espn"|"unknown",
 "intent": "approve"|"reject"|"move"|"question"|"trade_eval"|"trade_ideas"|"other",
 "refs": [question labels like "Q6" or "E2" the message refers to],
 "drop": [our players to drop, for a move], "add": [players to pick up, for a move; empty = best available],
 "position": "position wanted for the pickup (F, D, G, C, LW, RW) or empty for the dropped player's",
 "only_if_better": true if the move should only happen when a free agent is better than the dropped player,
 "give": [our players offered in a trade], "get": [players wanted from the other team],
 "other_team": "the other team as written (e.g. T4, Thumb, 2, OSG) or empty",
 "question": "the owner's question restated in one line, or empty"}
Rules: Q labels are Yahoo, E labels are ESPN. "yes", "sure", "do it", "go ahead", "ok the hofer one" approve the
open question they point at (match player names to the open questions). "no", "skip", "pass" reject. Approve and
reject only answer an open question: a message about players who aren't in any open question is never approve or
reject. Asking to drop someone and/or pick someone up ("drop X and grab the best D", "swap X for Y") is move; "unless
we find someone better" or "if there's anyone better" sets only_if_better. A message about keeping or benching a
player with no move asked for is question. Resolve "him", "that guy" etc. from the recent log lines (the bot's
latest texts to the owner), and set league from them when the message doesn't say.
"what about X for Y", "would T4 do X for Y" is trade_eval. "any trade ideas" is trade_ideas. If the message names
no label but clearly matches exactly one open question, put that label in refs.

Examples:
open: Q6 add Joel Hofer drop Jet Greaves | msg: "sure do the hofer one"
{"league":"yahoo","intent":"approve","refs":["Q6"],"give":[],"get":[],"other_team":"","question":""}
open: E4 add Joel Hofer drop Brandon Bussi | msg: "nah"
{"league":"espn","intent":"reject","refs":["E4"],"give":[],"get":[],"other_team":"","question":""}
msg: "would thumb take knight for chychrun?"
{"league":"yahoo","intent":"trade_eval","refs":[],"give":["Spencer Knight"],"get":["Jakob Chychrun"],"other_team":"Thumb","question":"Would they accept Knight for Chychrun?"}
msg: "Marchand is out for the season, drop him and pick up the next best forward"
{"league":"unknown","intent":"move","refs":[],"drop":["Brad Marchand"],"add":[],"position":"F","only_if_better":false,"give":[],"get":[],"other_team":"","question":""}
open: E4 add Joel Hofer drop Brandon Bussi | msg: "keep Demidov on the bench unless we find a better free agent to replace him"
{"league":"unknown","intent":"move","refs":[],"drop":["Ivan Demidov"],"add":[],"position":"","only_if_better":true,"give":[],"get":[],"other_team":"","question":""}
msg: "why is bussi starting over wedgewood in espn"
{"league":"espn","intent":"question","refs":[],"give":[],"get":[],"other_team":"","question":"Why is Bussi starting over Wedgewood?"}"""


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, **kw)


def open_questions():
    out = {}
    for league, log in LOGS.items():
        text = log.read_text() if log.exists() else ""
        done = set(DONE_RE.findall(text))
        for label, add, info, drop in Q_RE.findall(text):
            if label not in done:
                out[label] = {"league": league, "add": add.strip(), "info": info, "drop": drop.strip()}
    return out


def roster(league):
    try:
        return [r["name"] for r in json.loads(STATES[league].read_text())["roster"]]
    except (OSError, KeyError, json.JSONDecodeError):
        return []


def log(league, text):
    if DRY:
        return print(f"[dry log {league}] {text}")
    run([sys.executable, "manage.py"] + (["--league", "espn"] if league == "espn" else []) + ["log", text])


def send(msg):
    if DRY:
        return print(f"[dry text] {msg}")
    run([str(REPO / "scripts/imessage_send.sh"), msg])


def tail(league, n=12):
    p = LOGS[league]
    return "\n".join(p.read_text().splitlines()[-n:]) if p.exists() else ""


def yahoo_team_id(name):
    """T4 / 4 / a team name or short form from data/team_aliases.json -> Yahoo team number."""
    m = re.fullmatch(r"[Tt]?(\d{1,2})", name.strip())
    if m:
        return int(m.group(1))
    alias = team_alias.scrub(name).strip()
    m = re.fullmatch(r"T(\d{1,2})", alias)
    return int(m.group(1)) if m else None


class BusyError(Exception):
    pass


@contextlib.contextmanager
def run_lock():
    """The scheduled runs' lock, held only around the bots (they share one browser profile and change rosters),
    not around the LLM: it thinks for minutes, and a scheduled run gives up after waiting 10 min for the lock."""
    lock = REPO / "data/.run.lock"
    for _ in range(60):
        try:
            lock.mkdir()
            break
        except FileExistsError:
            time.sleep(10)
    else:
        raise BusyError
    try:
        yield
    finally:
        lock.rmdir()


def bot(league, *args, timeout=180):
    """yahoo_bot.py / espn_bot.py under the run lock."""
    exe = [str(REPO / ".venv/bin/python"), "yahoo_bot.py"] if league == "yahoo" else [sys.executable, "espn_bot.py"]
    with run_lock():
        return run(exe + list(args), timeout=timeout)


def league_plan(league):
    """The league's report plan: our roster and the free-agent pool (Yahoo reads the site, under the run lock)."""
    if league == "espn":
        return moves.espn_plan()
    r = bot("yahoo", "report", timeout=300)
    if "RESULT_JSON " not in r.stdout:
        raise RuntimeError("Yahoo report failed: " + (r.stdout + r.stderr).strip()[-200:])
    return json.loads(r.stdout.split("RESULT_JSON ", 1)[1].strip().splitlines()[0])["plan"]


def move(intent, text, league):
    """Owner-directed add/drops: the owner asking is the approval; moves.pick chooses the player."""
    drops = [d for d in intent.get("drop") or [] if isinstance(d, str) and d.strip()]
    adds = [a for a in intent.get("add") or [] if isinstance(a, str) and a.strip()]
    if not drops:
        return None, "Who should I drop? e.g. \"drop Marchand, add the best F\"."
    if league not in ("yahoo", "espn"):  # whichever of our rosters has the dropped players
        found = [lg for lg in ("yahoo", "espn") if all(moves.find(d, [{"name": n} for n in roster(lg)]) for d in drops)]
        if len(found) != 1:
            return None, f"Which league, Yahoo or ESPN? ({', '.join(drops)})"
        league = found[0]
    prefix = "ESPN: " if league == "espn" else ""
    position, better = str(intent.get("position") or ""), bool(intent.get("only_if_better"))
    plan = league_plan(league)
    lines, taken, queue = [], set(), moves.load_queue()
    for m in queue:  # players already promised to earlier queued moves (Monday's run picks in this order too)
        _, a, _ = moves.pick(plan, m["drop"], m.get("add"), m.get("position", ""), m.get("only_if_better", False), taken)
        if a:
            taken.add(a["name"])
    for i, drop in enumerate(drops):
        add = adds[i] if i < len(adds) else None
        d, a, why = moves.pick(plan, drop, add, position, better, taken)
        if why:
            lines.append(f"Kept {d['name'] if d else drop}: {why}.")
            continue
        taken.add(a["name"])
        what = moves.describe(d, a)
        if league == "espn" and date.today().weekday() != 0:
            queue.append({"drop": d["name"], "add": add and a["name"], "position": position, "only_if_better": better,
                          "requested": datetime.now().isoformat(timespec="minutes"), "text": text[:200]})
            lines.append(f"Queued for Monday (ESPN add/drops are Monday-only): {what}."
                         + ("" if add else " Monday's run re-picks the best available then."))
            continue
        r = bot(league, "swap", a["name"], d["name"], *(["--dry-run"] if DRY else []), timeout=600)
        res = json.loads(r.stdout.split("RESULT_JSON ", 1)[1]) if "RESULT_JSON " in r.stdout else {"did": [], "skipped": [r.stderr[-200:] or "bot failed"]}
        lines.append(("Done: " + "; ".join(res["did"]) + ".") if res["did"] else f"Couldn't {what}: " + "; ".join(res["skipped"])[:250])
    if DRY:
        print(f"[dry queue] {json.dumps(queue)}")
    else:
        moves.save_queue(queue)
    log(league, f"Owner asked for a move: {text[:200]} | " + " ".join(lines))
    return league, prefix + " ".join(lines)


def handle(text):
    qs = open_questions()
    context = ("Open questions:\n" + ("\n".join(f"{k}: add {v['add']} ({v['info']}), drop {v['drop']}" for k, v in qs.items()) or "none")
               + "\n\nOur Yahoo roster: " + ", ".join(roster("yahoo"))
               + "\nOur ESPN roster: " + ", ".join(roster("espn"))
               # what the bot last told the owner, so "him" / "that one" in a reply can be resolved
               + "\n\nRecent Yahoo log (newest last):\n" + tail("yahoo", 4)
               + "\n\nRecent ESPN log (newest last):\n" + tail("espn", 4))
    intent = llm.complete_json(f"{context}\n\nOwner's message: {text}", system=SYSTEM, max_tokens=300)
    kind, league = intent.get("intent"), intent.get("league")
    refs = [r.upper() for r in intent.get("refs") or [] if isinstance(r, str)]

    if kind in ("approve", "reject"):
        refs = [r for r in refs if r in qs]
        if not refs and len(qs) == 1 and len(text.split()) <= 3:  # a bare "yes"/"no" can only mean the one open question
            refs = list(qs)
        if len(refs) != 1:
            open_list = "; ".join(f"{k} (add {v['add']}/drop {v['drop']})" for k, v in qs.items()) or "none"
            return None, f"Which one? Open questions: {open_list}. Reply e.g. \"yes {next(iter(qs), 'Q1')}\"."
        q = qs[refs[0]]
        league = q["league"]
        if kind == "reject":
            log(league, f"Resolved {refs[0]}: owner declined add {q['add']} / drop {q['drop']}.")
            return league, f"{'ESPN: ' if league == 'espn' else ''}OK, skipping {refs[0]} (keeping {q['drop']})."
        r = bot(league, "swap", q["add"], q["drop"], *(["--dry-run"] if DRY else []), timeout=600)
        res = json.loads(r.stdout.split("RESULT_JSON ", 1)[1]) if "RESULT_JSON " in r.stdout else {"did": [], "skipped": [r.stderr[-200:] or "bot failed"]}
        if res["did"]:
            log(league, f"Resolved {refs[0]}: owner approved; " + "; ".join(res["did"]))
            return league, f"{'ESPN: ' if league == 'espn' else ''}Done ({refs[0]}): " + "; ".join(res["did"]) + "."
        log(league, f"{refs[0]} approved but not done: " + "; ".join(res["skipped"]))
        return league, f"{'ESPN: ' if league == 'espn' else ''}Couldn't do {refs[0]}: " + "; ".join(res["skipped"])[:250]

    if kind == "move":
        return move(intent, text, league)

    if kind in ("trade_eval", "trade_ideas"):
        if league not in ("yahoo", "espn"):
            return None, "Which league, Yahoo or ESPN?"
        mg = [sys.executable, "manage.py"] + (["--league", "espn"] if league == "espn" else [])
        if kind == "trade_ideas":
            if league == "yahoo":
                teams = []
                for n in range(1, 13):
                    if n != 11:
                        t = bot("yahoo", "team", str(n)).stdout.strip()
                        if t:
                            teams += ["--team", f"T{n}", t]
                r = run(mg + ["trade-ideas"] + teams, timeout=600)
            else:
                r = run(mg + ["trade-ideas"], timeout=300)
            facts = r.stdout.strip()
        else:
            give, get = intent.get("give") or [], intent.get("get") or []
            other = intent.get("other_team") or ""
            if not give or not get or not other:
                return league, "Which players each way, and with which team? e.g. \"Knight for Chychrun with T4\"."
            if league == "yahoo":
                tid = yahoo_team_id(other)
                if not tid:
                    return league, f"Which team is \"{other}\"? Use its number, e.g. T4."
                theirs = bot("yahoo", "team", str(tid)).stdout.strip()
                r = run(mg + ["trade", "--give", ";".join(give), "--get", ";".join(get), "--theirs", theirs])
            else:
                m = re.search(r"\d{1,2}", other)
                if not m:
                    return league, f"Which ESPN team is \"{other}\"? Use its team number (1-6)."
                r = run(mg + ["trade", "--give", ";".join(give), "--get", ";".join(get), "--team", m.group(0)])
            line = (r.stdout.strip().splitlines() or [r.stderr.strip()])[-1]
            try:
                t = json.loads(line)
                facts = (f"We give {', '.join(f'{n} ({p}, {v} ROS FP)' for n, p, v in t['give'])}; we get "
                         f"{', '.join(f'{n} ({p}, {v} ROS FP)' for n, p, v in t['get'])}. OUR best lineup changes by "
                         f"{t['us']:+} FP; THEIR best lineup changes by {t['them']:+} FP. Verdict: {t['verdict']}.")
            except (json.JSONDecodeError, KeyError):
                facts = line
        answer = llm.complete(
            f"Owner asked: {text}\nOur model's trade math (rest-of-season fantasy points):\n{facts}\n\nWrite a short text reply that "
            "states the verdict exactly as given, the two lineup changes (ours and theirs, don't swap them), and only if "
            "the verdict says worth offering, a one-sentence note the owner could paste into the offer explaining why "
            "it helps the other team. Use only "
            "these numbers; label anything else as opinion. Under 600 characters, no markdown.", max_tokens=350)
        log(league, f"Owner asked about a trade: {text} | model: {facts[:400]}")
        return league, ("ESPN: " if league == "espn" else "") + answer.strip()

    if kind == "question":
        lg = league if league in ("yahoo", "espn") else "yahoo"
        state = run([sys.executable, "manage.py"] + (["--league", "espn"] if lg == "espn" else []) + ["roster"]).stdout
        answer = llm.complete(
            f"Owner asked: {text}\n\nOur {lg} roster with model values (FP/G, rest-of-season FP):\n{state}\n\n"
            f"Recent {lg} log:\n{tail(lg)}\n\nAnswer briefly as a text message, using only this information; say so if "
            "it isn't enough to answer. Under 500 characters, no markdown.", max_tokens=300)
        return lg, ("ESPN: " if lg == "espn" else "") + answer.strip()

    return None, ("I can approve or skip open questions (Q../E..), evaluate trades (\"Knight for Chychrun with T4?\"), "
                  "suggest trades, or answer questions about the teams. What would you like?")


def main():
    text = " ".join(sys.argv[1:]).strip()
    if not text:
        sys.exit(__doc__)
    try:
        league, reply = handle(text)
    except BusyError:
        league, reply = None, "Busy with a scheduled run; send that again in a few minutes."
    except Exception as e:  # LLM down or unparseable: say so instead of going quiet
        league, reply = None, f"Sorry, I couldn't process that ({type(e).__name__}). Try again, or rephrase."
    send(reply)
    if league:
        log(league, f"Owner texted: {text[:200]} | replied: {reply[:300]}")
    print(reply)


if __name__ == "__main__":
    main()
