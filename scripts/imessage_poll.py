"""Check Messages for new texts from the owner; if any, hand them to scripts/reply_auto.py.

Run by launchd every 2 minutes. Needs Full Disk Access for the python3 that runs it (to read chat.db).
Messages sent by Claude start with the configured prefix and are ignored. The first run only records
the current position, so old messages never trigger anything. Messages iCloud re-syncs under new ROWIDs are
skipped by date. Also resends texts that scripts/imessage_send.sh queued in data/imessage_outbox.jsonl.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path("/Users/zackholmberg/dev/yahoo-fantasy-hockey")
CFG = json.loads((REPO / "data/imessage.json").read_text())
STATE = REPO / "data/imessage_state.json"
OUTBOX = REPO / "data/imessage_outbox.jsonl"
DB = Path.home() / "Library/Messages/chat.db"


def body(text, blob):
    if text:
        return text
    if not blob or b"NSString" not in blob:
        return ""
    data = blob.split(b"NSString", 1)[1][5:]
    if data[0] == 0x81:
        n, data = int.from_bytes(data[1:3], "little"), data[3:]
    else:
        n, data = data[0], data[1:]
    return data[:n].decode("utf-8", "ignore")


def flush_outbox():
    """Resend texts imessage_send.sh couldn't deliver; keep any that still fail for the next poll, up to 6 hours."""
    if not OUTBOX.exists():
        return
    pending = [json.loads(m) for m in OUTBOX.read_text().splitlines() if m.strip()]
    OUTBOX.unlink()
    failed = [(t, msg) for t, msg in pending if subprocess.run(
        [str(REPO / "scripts/imessage_send.sh"), msg], env=os.environ | {"IMESSAGE_NO_QUEUE": "1"}).returncode]
    keep = [(t, msg) for t, msg in failed if time.time() - t < 6 * 3600]
    if keep:
        with OUTBOX.open("a") as f:
            f.write("".join(json.dumps([t, msg]) + "\n" for t, msg in keep))
    if len(keep) < len(failed):
        print(f"imessage_poll: gave up on {len(failed) - len(keep)} queued text(s) after 6 hours", file=sys.stderr)


def main():
    flush_outbox()
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        """select m.ROWID, m.text, m.attributedBody, m.date from message m
           join chat_message_join cmj on cmj.message_id = m.ROWID
           join chat c on c.ROWID = cmj.chat_id
           where c.chat_identifier = ? and m.ROWID > ? order by m.ROWID""",
        (CFG["handle"], state.get("last_rowid", -1))).fetchall()
    if "last_rowid" not in state:
        state["last_rowid"] = max((r[0] for r in rows), default=0)
        STATE.write_text(json.dumps(state))
        return
    if not rows:
        return
    # iCloud sometimes re-inserts days-old messages under new ROWIDs: skip anything well before the newest seen
    cutoff = state.get("last_date", 0) - 3600 * 10**9  # chat.db dates are ns; an hour's slack for late sync
    state["last_rowid"] = rows[-1][0]
    state["last_date"] = max([state.get("last_date", 0)] + [r[3] or 0 for r in rows])
    STATE.write_text(json.dumps(state))
    rows = [r for r in rows if (r[3] or 0) > cutoff]
    # a self-chat stores each message twice (sent + received): keep one copy
    texts = list(dict.fromkeys(t for t in (body(r[1], r[2]).strip() for r in rows)
                               if t and not t.startswith(CFG["prefix"].strip())))
    if texts:
        # scripts + the LLM layer (llm.py) handle replies; data/llm.json picks the local model or Claude
        subprocess.run([str(REPO / "scripts/reply_auto.py"), "\n".join(texts)])


if __name__ == "__main__":
    main()
