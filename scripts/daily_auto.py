#!/usr/bin/python3
"""Scheduled league runs without Claude. Usage: scripts/daily_auto.py yahoo [morning|evening] | espn

yahoo: yahoo_bot.py apply (Playwright, owner's saved Yahoo session) sets the lineup/IR and makes AUTO-OK moves.
espn:  manage.py --league espn report --fetch reads ESPN's API; espn_bot.py apply makes the report's ACTIONS through
       ESPN's write API (a locked lineup or other refusal is texted to the owner and retried next run).
Both:  log to the season log, number questions for the owner (Q.. / E..), and text the owner only when something
       happened, needs a decision, or broke. llm.py (driver in data/llm.json: local Qwen or Claude) phrases
       the text; a plain template is the fallback. Owner replies still go to Claude via imessage_poll.py.
"""
import json
import re
import subprocess
import sys
import urllib.request
from datetime import date, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
import moves  # noqa: E402
LOG_DIR = REPO / "data/run_logs"


def run(cmd, **kw):
    return subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, **kw)


def log_line(league, text):
    run([sys.executable, "manage.py"] + (["--league", "espn"] if league == "espn" else []) + ["log", text])


def text_owner(msg):
    r = run([str(REPO / "scripts/imessage_send.sh"), msg])
    return r.returncode == 0


def phrase(facts, prefix):
    """One short, phone-readable text from the facts via the LLM layer (llm.py); template if it fails or drops a label."""
    template = prefix + " ".join(facts)
    try:
        sys.path.insert(0, str(REPO))
        import llm
        out = llm.complete("Rewrite these fantasy hockey bot notes as ONE short, friendly text message to the team "
                           "owner. Keep every player name, number and question label (like Q5 or E2) exactly. No "
                           "preamble, no markdown, under 450 characters.\n\nNotes:\n" + "\n".join(facts),
                           max_tokens=300).strip().strip('"')
        labels = [w for f in facts for w in f.replace(":", " ").split() if w[:1] in "QE" and w[1:].isdigit()]
        if out and len(out) < 600 and all(l in out for l in labels):
            return prefix + out
    except Exception:
        pass
    return template


def questions(plan, league):
    """Question lines for the report's ASK swaps, skipping any already asked and still open in the season log."""
    log = (REPO / ("espn/data/season_log.md" if league == "espn" else "data/season_log.md"))
    text = log.read_text() if log.exists() else ""
    resolved = set(re.findall(r"\bResolved ([QE]\d+)\b", text))
    asked = {(a.strip(), d.strip()) for lab, a, d in re.findall(r"\b([QE]\d+): add (.+?) \([^)]*\), drop (.+?)\?", text)
             if lab not in resolved}
    out, n = [], plan["next_question"]
    for q in plan["ask"]:
        if (q["add"], q["drop"]) in asked:
            continue
        out.append(f"{plan['question_prefix']}{n}: add {q['add']} ({q['add_pos']}, {q['add_team']}), drop {q['drop']}? "
                   f"(+{q['gain']} rest-of-season FP). Reply yes/no.")
        n += 1
    return out


def trade_ideas(league):
    """Mondays: up to two 1-for-1 trades that improve both sides' best lineup (never sent; the owner decides)."""
    if datetime.now().weekday() != 0:
        return []
    mg = [sys.executable, "manage.py"] + (["--league", "espn"] if league == "espn" else [])
    args = []
    if league == "yahoo":
        for n in range(1, 13):
            if n == 11:
                continue
            t = run([str(REPO / ".venv/bin/python"), "yahoo_bot.py", "team", str(n)], timeout=180).stdout.strip()
            if t:
                args += ["--team", f"T{n}", t]
    r = run(mg + ["trade-ideas"] + args, timeout=900)
    try:
        ideas = json.loads(r.stdout.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        return []
    team = (lambda t: f"T{t}" if not str(t).startswith("T") else t) if league == "yahoo" else (lambda t: f"team {t}")
    return [f"Trade idea: {i['give'][0][0]} to {team(i['team'])} for {i['get'][0][0]} (our lineup {i['us']:+.0f}, "
            f"theirs {i['them']:+.0f} rest-of-season FP){' - note: gives up a protected player' if i['protected_give'] else ''}. "
            "Reply if you want it checked or a note for the offer."
            for i in ideas[:2]]


def yahoo():
    r = run([str(REPO / ".venv/bin/python"), "yahoo_bot.py", "apply"], timeout=900)
    if "RESULT_JSON " not in r.stdout:
        err = (r.stdout + r.stderr).strip().splitlines()[-1:] or ["unknown error"]
        log_line("yahoo", f"Auto run failed: {err[0]}")
        signed_out = "not signed in" in r.stdout + r.stderr
        text_owner("Yahoo auto run failed: " + ("Yahoo signed the bot out, so Claude is covering today's run. To fix: "
                    "run `.venv/bin/python yahoo_bot.py login` on the Mac and sign in." if signed_out else err[0][:200]))
        return r.stdout + r.stderr, True  # fall back to the Claude run so the lineup still gets set
    res = json.loads(r.stdout.split("RESULT_JSON ", 1)[1])
    plan = res["plan"]
    facts = []
    lineup = [d for d in res["did"] if "->" in d]
    moves = [d for d in res["did"] if "->" not in d]
    if lineup:
        facts.append(f"Set today's lineup ({len(lineup)} change{'s' * (len(lineup) != 1)}): " + "; ".join(lineup) + ".")
    facts += [m[0].upper() + m[1:] + "." for m in moves]
    facts += questions(plan, "yahoo")
    for s in plan.get("ask_text", []):
        if not s.startswith("[ASK]"):
            facts.append(s + ".")
    if res["skipped"]:
        facts.append("Couldn't do: " + "; ".join(res["skipped"]) + ".")
    if res.get("left_after"):
        facts.append("Re-check still shows work left; I'll retry next run.")
    facts += trade_ideas("yahoo")
    summary = " ".join(facts) or "Quiet day: lineup already right, no moves."
    log_line("yahoo", "Auto run: " + summary)
    if facts:
        text_owner(phrase(facts, ""))
    else:  # the owner wants to know the check ran even when there's nothing to do
        mode = sys.argv[2] if len(sys.argv) > 2 else "morning"
        text_owner(f"Yahoo {mode} check done: lineup already right, no actions needed.")
    return r.stdout, False


def espn_queued():
    """Monday: make the owner's add/drops queued mid-week (scripts/reply_auto.py), re-picking 'best available' now."""
    queue = moves.load_queue()
    if not queue or date.today().weekday() != 0:
        return []
    try:
        plan = moves.espn_plan()
    except RuntimeError as e:
        return [f"Couldn't make your queued moves ({e}); they stay queued."]
    facts, taken = [], set()
    for m in queue:
        d, a, why = moves.pick(plan, m["drop"], m.get("add"), m.get("position", ""), m.get("only_if_better", False), taken)
        if why:
            facts.append(f"Queued move not made, kept {d['name'] if d else m['drop']}: {why}.")
            continue
        taken.add(a["name"])
        w = run([sys.executable, "espn_bot.py", "swap", a["name"], d["name"]], timeout=600)
        res = json.loads(w.stdout.split("RESULT_JSON ", 1)[1]) if "RESULT_JSON " in w.stdout else {"did": [], "skipped": [(w.stdout + w.stderr).strip()[-200:]]}
        facts.append(("Your queued move: " + "; ".join(res["did"]) + ".") if res["did"]
                     else f"Your queued move failed ({moves.describe(d, a)}): " + "; ".join(res["skipped"])[:200] + ".")
    moves.save_queue([])  # made or reported either way; the owner can ask again
    return facts


def espn():
    queued = espn_queued()  # before the report, so it plans around the new roster
    r = run([sys.executable, "manage.py", "--league", "espn", "report", "--fetch", "--json"], timeout=300)
    if "PLAN_JSON " not in r.stdout:
        err = (r.stdout + r.stderr).strip().splitlines()[-1:] or ["unknown error"]
        log_line("espn", " ".join(queued + [f"Auto run failed: {err[0]}"]))
        text_owner("ESPN: " + " ".join(queued + ["Auto run failed: " + err[0][:200]]))
        return r.stdout + r.stderr, False
    plan = json.loads(r.stdout.split("PLAN_JSON ", 1)[1])
    if plan.get("held"):  # add/drops are Monday-only on ESPN: log what waits, don't text about it
        log_line("espn", "Held for Monday's run (add/drops are Monday-only): " + "; ".join(plan["held"])[:300])
    if plan["lineup"] or plan["ir"] or plan["swaps"]:
        w = run([sys.executable, "espn_bot.py", "apply"], timeout=600)
        if "RESULT_JSON " not in w.stdout:
            err = (w.stdout + w.stderr).strip().splitlines()[-1:] or ["unknown error"]
            log_line("espn", f"Auto run: espn_bot failed: {err[0]}")
            text_owner("ESPN: changes failed: " + err[0][:200])
            return r.stdout + w.stdout + w.stderr, False
        res = json.loads(w.stdout.split("RESULT_JSON ", 1)[1])
        facts = queued + [d[0].upper() + d[1:] + "." for d in res["did"]]
        # a locked weekly lineup is expected (e.g. Sunday): log it, retry next run, don't text about it alone
        locked = [x for x in res["skipped"] if "is locked" in x]
        skipped = [x for x in res["skipped"] if x not in locked]
        if skipped:
            facts.append("Couldn't do: " + "; ".join(skipped) + ".")
        if locked:
            log_line("espn", "Lineup locked until the week opens; will retry next run: " + "; ".join(locked)[:300])
        if res.get("left_after"):
            facts.append("Re-check still shows work left; I'll retry next run.")
        facts += questions(plan, "espn")
        facts += trade_ideas("espn")
        if facts:
            log_line("espn", "Auto run: " + " ".join(facts))
            text_owner(phrase(facts, "ESPN: "))
        else:
            text_owner(espn_quiet(plan))
        return r.stdout + w.stdout, False
    facts = queued + questions(plan, "espn")
    facts += [s + "." for s in plan.get("ask_text", []) if not s.startswith("[ASK]")]
    facts += trade_ideas("espn")
    log_line("espn", "Auto run: " + (" ".join(facts) or "quiet day, nothing to do."))
    if facts:
        text_owner(phrase(facts, "ESPN: "))
    else:
        text_owner(espn_quiet(plan))
    return r.stdout, False


def espn_quiet(plan):
    """Quiet-day text: the owner wants to know the check ran even when there's nothing to do."""
    held = len(plan.get("held", []))
    return ("ESPN check done: no actions needed" +
            (f" ({held} add/drop{'s' * (held != 1)} held for Monday)." if held else "."))


def main():
    league = sys.argv[1] if len(sys.argv) > 1 else ""
    if league not in ("yahoo", "espn"):
        sys.exit(__doc__)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    lock = REPO / "data/.run.lock"
    for _ in range(60):  # same lock as the Claude runs: one run at a time
        try:
            lock.mkdir()
            break
        except FileExistsError:
            __import__("time").sleep(10)
    else:
        sys.exit("daily_auto: another run holds data/.run.lock")
    try:
        out, handoff = yahoo() if league == "yahoo" else espn()
    finally:
        lock.rmdir()
    if handoff:  # daily_run.sh takes the lock itself
        mode = sys.argv[2] if len(sys.argv) > 2 else "morning"
        out += run([str(REPO / "scripts/daily_run.sh"), mode], timeout=3600).stdout
    with (LOG_DIR / f"{datetime.now():%Y-%m-%d}_auto_{league}.log").open("a") as f:
        f.write(f"=== {datetime.now()}\n{out}\n")


if __name__ == "__main__":
    main()
