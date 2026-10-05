#!/usr/bin/python3
"""Handle the owner's iMessage reply without a Claude agent. Usage: scripts/reply_auto.py "<owner's text>"

1. Context: open questions (Q.. Yahoo / E.. ESPN) parsed from the season logs, both rosters, recent log lines.
2. Understand: the LLM layer (llm.py; driver in data/llm.json) turns the free-form text into one intent as JSON.
3. Check: the script validates it (the question exists and is open, players are on the right rosters, the league
   is known). Anything that doesn't check out gets a clarifying text, never a guess.
4. Act: approved add/drops run through yahoo_bot.py / espn_bot.py swap; trade questions run manage.py trade /
   trade-ideas. Trades are never sent (owner-only), so the reply includes a ready-to-paste note.
5. Reply: the LLM phrases the answer from what the scripts found; logged in the league's season log.
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import llm  # noqa: E402
import team_alias  # noqa: E402

LOGS = {"yahoo": REPO / "data/season_log.md", "espn": REPO / "espn/data/season_log.md"}
STATES = {"yahoo": REPO / "data/season_state.json", "espn": REPO / "espn/data/season_state.json"}
DRY = bool(os.environ.get("REPLY_DRY"))  # test mode: no texts, no log lines, bot swaps as --dry-run
Q_RE = re.compile(r"\b([QE]\d+): add (.+?) \(([^)]*)\), drop (.+?)\?")
DONE_RE = re.compile(r"\bResolved ([QE]\d+)\b")

SYSTEM = """You read text messages from the owner of two fantasy hockey teams (a Yahoo league and an ESPN league)
and output what they want as JSON. You never decide moves yourself. Output exactly these keys:
{"league": "yahoo"|"espn"|"unknown", "intent": "approve"|"reject"|"question"|"trade_eval"|"trade_ideas"|"other",
 "refs": [question labels like "Q6" or "E2" the message refers to],
 "give": [our players offered in a trade], "get": [players wanted from the other team],
 "other_team": "the other team as written (e.g. T4, Thumb, 2, OSG) or empty",
 "question": "the owner's question restated in one line, or empty"}
Rules: Q labels are Yahoo, E labels are ESPN. "yes", "sure", "do it", "go ahead", "ok the hofer one" approve the
open question they point at (match player names to the open questions). "no", "skip", "pass" reject.
"what about X for Y", "would T4 do X for Y" is trade_eval. "any trade ideas" is trade_ideas. If the message names
no label but clearly matches exactly one open question, put that label in refs.

Examples:
open: Q6 add Joel Hofer drop Jet Greaves | msg: "sure do the hofer one"
{"league":"yahoo","intent":"approve","refs":["Q6"],"give":[],"get":[],"other_team":"","question":""}
open: E4 add Joel Hofer drop Brandon Bussi | msg: "nah"
{"league":"espn","intent":"reject","refs":["E4"],"give":[],"get":[],"other_team":"","question":""}
msg: "would thumb take knight for chychrun?"
{"league":"yahoo","intent":"trade_eval","refs":[],"give":["Spencer Knight"],"get":["Jakob Chychrun"],"other_team":"Thumb","question":"Would they accept Knight for Chychrun?"}
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


def handle(text):
    qs = open_questions()
    context = ("Open questions:\n" + ("\n".join(f"{k}: add {v['add']} ({v['info']}), drop {v['drop']}" for k, v in qs.items()) or "none")
               + "\n\nOur Yahoo roster: " + ", ".join(roster("yahoo"))
               + "\nOur ESPN roster: " + ", ".join(roster("espn")))
    intent = llm.complete_json(f"{context}\n\nOwner's message: {text}", system=SYSTEM, max_tokens=300)
    kind, league = intent.get("intent"), intent.get("league")
    refs = [r.upper() for r in intent.get("refs") or [] if isinstance(r, str)]

    if kind in ("approve", "reject"):
        refs = [r for r in refs if r in qs]
        if not refs and len(qs) == 1:
            refs = list(qs)
        if len(refs) != 1:
            open_list = "; ".join(f"{k} (add {v['add']}/drop {v['drop']})" for k, v in qs.items()) or "none"
            return None, f"Which one? Open questions: {open_list}. Reply e.g. \"yes {next(iter(qs), 'Q1')}\"."
        q = qs[refs[0]]
        league = q["league"]
        if kind == "reject":
            log(league, f"Resolved {refs[0]}: owner declined add {q['add']} / drop {q['drop']}.")
            return league, f"{'ESPN: ' if league == 'espn' else ''}OK, skipping {refs[0]} (keeping {q['drop']})."
        bot = ([str(REPO / ".venv/bin/python"), "yahoo_bot.py"] if league == "yahoo" else [sys.executable, "espn_bot.py"])
        r = run(bot + ["swap", q["add"], q["drop"]] + (["--dry-run"] if DRY else []), timeout=600)
        res = json.loads(r.stdout.split("RESULT_JSON ", 1)[1]) if "RESULT_JSON " in r.stdout else {"did": [], "skipped": [r.stderr[-200:] or "bot failed"]}
        if res["did"]:
            log(league, f"Resolved {refs[0]}: owner approved; " + "; ".join(res["did"]))
            return league, f"{'ESPN: ' if league == 'espn' else ''}Done ({refs[0]}): " + "; ".join(res["did"]) + "."
        log(league, f"{refs[0]} approved but not done: " + "; ".join(res["skipped"]))
        return league, f"{'ESPN: ' if league == 'espn' else ''}Couldn't do {refs[0]}: " + "; ".join(res["skipped"])[:250]

    if kind in ("trade_eval", "trade_ideas"):
        if league not in ("yahoo", "espn"):
            return None, "Which league, Yahoo or ESPN?"
        mg = [sys.executable, "manage.py"] + (["--league", "espn"] if league == "espn" else [])
        if kind == "trade_ideas":
            if league == "yahoo":
                teams = []
                for n in range(1, 13):
                    if n != 11:
                        t = run([str(REPO / ".venv/bin/python"), "yahoo_bot.py", "team", str(n)], timeout=180).stdout.strip()
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
                theirs = run([str(REPO / ".venv/bin/python"), "yahoo_bot.py", "team", str(tid)], timeout=180).stdout.strip()
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
    lock = REPO / "data/.run.lock"  # same lock as the scheduled runs: never act on a roster mid-run
    for _ in range(60):
        try:
            lock.mkdir()
            break
        except FileExistsError:
            __import__("time").sleep(10)
    else:
        send("Busy with a scheduled run; send that again in a few minutes.")
        return
    try:
        league, reply = handle(text)
    except Exception as e:  # LLM down or unparseable: say so instead of going quiet
        league, reply = None, f"Sorry, I couldn't process that ({type(e).__name__}). Try again, or rephrase."
    finally:
        lock.rmdir()
    send(reply)
    if league:
        log(league, f"Owner texted: {text[:200]} | replied: {reply[:300]}")
    print(reply)


if __name__ == "__main__":
    main()
