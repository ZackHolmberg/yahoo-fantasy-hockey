"""Check Messages for new texts from the owner; if any, start a reply run.

Run by launchd every 2 minutes. Needs Full Disk Access for the python3 that runs it (to read chat.db).
Messages sent by Claude start with the configured prefix and are ignored. The first run only records
the current position, so old messages never trigger anything.
"""
import json
import sqlite3
import subprocess
from pathlib import Path

REPO = Path("/Users/zackholmberg/dev/yahoo-fantasy-hockey")
CFG = json.loads((REPO / "data/imessage.json").read_text())
STATE = REPO / "data/imessage_state.json"
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


def main():
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    rows = con.execute(
        """select m.ROWID, m.text, m.attributedBody from message m
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
    state["last_rowid"] = rows[-1][0]
    STATE.write_text(json.dumps(state))
    # a self-chat stores each message twice (sent + received): keep one copy
    texts = list(dict.fromkeys(t for t in (body(r[1], r[2]).strip() for r in rows)
                               if t and not t.startswith(CFG["prefix"].strip())))
    if texts:
        subprocess.run([str(REPO / "scripts/daily_run.sh"), "reply", "\n".join(texts)])


if __name__ == "__main__":
    main()
