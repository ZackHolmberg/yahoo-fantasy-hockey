#!/usr/bin/env python3
"""Show what a headless manager run did, as a readable timeline. Read-only.

  python3 scripts/show_run.py              # latest run
  python3 scripts/show_run.py reply        # latest reply run (or morning / evening)
  python3 scripts/show_run.py reply 2      # second-latest reply run
  python3 scripts/show_run.py --list       # recent runs
  python3 scripts/show_run.py <session-id> # a specific run
  add --full to include every tool result (default: only texts sent, errors, and log lines)
"""
import contextlib
import io
import json
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SESSIONS = Path.home() / ".claude/projects" / ("-" + str(REPO).strip("/").replace("/", "-").replace("_", "-"))
MARKER = "You are the in-season manager"


def load(path):
    rows = []
    for line in path.open():
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def prompt_of(rows):
    for d in rows:
        c = d.get("content") if d.get("type") == "queue-operation" else None
        if c is None and d.get("type") == "user":
            c = d["message"].get("content")
            if isinstance(c, list):
                c = " ".join(b.get("text", "") for b in c if isinstance(b, dict))
        if isinstance(c, str) and c:
            return c
    return ""


def mode_of(prompt):
    for m in ("Morning run", "Evening run", "replied by iMessage"):
        if m in prompt:
            return {"Morning run": "morning", "Evening run": "evening"}.get(m, "reply")
    return "?"


def runs():
    out = []
    for p in SESSIONS.glob("*.jsonl"):
        with p.open() as f:
            head = f.read(4000)
        if MARKER not in head:
            continue
        rows = load(p)
        pr = prompt_of(rows)
        ts = next((d["timestamp"] for d in rows if d.get("timestamp")), "")
        out.append({"path": p, "id": p.stem, "prompt": pr, "mode": mode_of(pr), "ts": ts, "rows": rows})
    return sorted(out, key=lambda r: r["ts"], reverse=True)


def local(ts):
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone().strftime("%a %m-%d %H:%M:%S")
    except ValueError:
        return ts


def owner_text(prompt):
    if "<<<" in prompt and ">>>" in prompt:
        return prompt.split("<<<", 1)[1].split(">>>", 1)[0]
    return ""


def result_text(b):
    c = b.get("content")
    if isinstance(c, list):
        c = "\n".join(x.get("text", "[image]") if isinstance(x, dict) else str(x) for x in c)
    return str(c or "")


def tool_line(b):
    name, inp = b["name"], b.get("input", {})
    short = name.replace("mcp__claude-in-chrome__", "chrome.")
    if name == "Bash":
        return f"$ {inp.get('command', '')}"
    if short == "chrome.computer":
        bits = [inp.get("action", "")]
        for k in ("text", "ref", "coordinate"):
            if inp.get(k) is not None:
                bits.append(f"{k}={inp[k]}")
        return f"{short} " + " ".join(map(str, bits))
    arg = inp.get("url") or inp.get("query") or inp.get("skill") or inp.get("file_path") or ""
    return f"{short} {arg}".rstrip()


def show(run, full):
    print(f"=== {run['mode']} run, {local(run['ts'])}  (session {run['id']})")
    msg = owner_text(run["prompt"])
    if msg:
        print(f"\nOWNER: {msg}")
    pending = {}
    for d in run["rows"]:
        m = d.get("message") or {}
        content = m.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text" and d.get("type") == "assistant":
                print(f"\n[{local(d.get('timestamp', ''))[-8:]}] {b['text'].strip()}")
            elif t == "tool_use":
                pending[b["id"]] = b
                print(f"    > {tool_line(b)[:300]}")
            elif t == "tool_result":
                src = pending.get(b.get("tool_use_id"), {})
                cmd = json.dumps(src.get("input", {}))
                text = result_text(b).strip()
                interesting = b.get("is_error") or "imessage_send" in cmd or "manage.py log" in cmd or "error" in text[:200].lower()
                if full or interesting:
                    tag = "ERROR" if b.get("is_error") else "result"
                    body = text if full else text[:600]
                    print("      " + f"{tag}: {body}".replace("\n", "\n      "))
    print()


def main():
    args = [a for a in sys.argv[1:] if a != "--full"]
    full = "--full" in sys.argv
    all_runs = runs()
    if not all_runs:
        sys.exit(f"no manager runs found in {SESSIONS}")
    if args and args[0] == "--list":
        for r in all_runs[:20]:
            print(f"{local(r['ts'])}  {r['mode']:8} {r['id']}  {' '.join(owner_text(r['prompt']).split())[:50]}")
        return
    if args and len(args[0]) > 20:
        match = [r for r in all_runs if r["id"].startswith(args[0])]
    else:
        mode = args[0] if args else None
        match = [r for r in all_runs if mode in (None, r["mode"])]
        n = int(args[1]) if len(args) > 1 else 1
        match = match[n - 1:n]
    if not match:
        sys.exit("no matching run (try --list)")
    show(match[0], full)


if __name__ == "__main__":
    sys.path.insert(0, str(REPO))
    from team_alias import scrub
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            main()
    finally:
        sys.stdout.write(scrub(buf.getvalue()))
