#!/bin/zsh
# Text the owner via Messages.app. Usage: scripts/imessage_send.sh "message"
# If the send errors (Messages.app wedges after days of uptime: AppleEvent -1712 / -10000), quit and
# relaunch Messages, then retry once, unless chat.db shows the first attempt went out after all.
cd /Users/zackholmberg/dev/yahoo-fantasy-hockey || exit 1
HANDLE=$(/usr/bin/python3 -c 'import json;print(json.load(open("data/imessage.json"))["handle"])')
PREFIX=$(/usr/bin/python3 -c 'import json;print(json.load(open("data/imessage.json"))["prefix"],end="")')
MSG=$(print -r -- "$PREFIX$1" | /usr/bin/python3 team_alias.py)

send() {
  /usr/bin/osascript - "$HANDLE" "$MSG" <<'OSA'
on run argv
  with timeout of 20 seconds
    tell application "Messages"
      -- macOS 27 errors (-10000) on any account property, so address the existing chat directly
      try
        set c to chat id ("any;-;" & (item 1 of argv))
      on error
        set c to participant (item 1 of argv) of (1st account whose service type = iMessage)
      end try
      send (item 2 of argv) to c
    end tell
  end timeout
end run
OSA
}

# exit 0 if the message is in chat.db from the last 5 minutes; 1 if not; 2 if chat.db is unreadable
already_sent() {
  /usr/bin/python3 - "$HANDLE" "$MSG" <<'PY'
import sqlite3, sys, time
from pathlib import Path
sys.path.insert(0, "scripts")
try:
    from imessage_poll import DB, body
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    since = int((time.time() - 978307200 - 300) * 1e9)  # Apple epoch, ns
    rows = con.execute(
        """select m.text, m.attributedBody from message m
           join chat_message_join cmj on cmj.message_id = m.ROWID
           join chat c on c.ROWID = cmj.chat_id
           where c.chat_identifier = ? and m.is_from_me = 1 and m.date > ?""",
        (sys.argv[1], since)).fetchall()
except Exception:
    sys.exit(2)
sys.exit(0 if any(body(t, b).strip() == sys.argv[2].strip() for t, b in rows) else 1)
PY
}

relaunch() {
  /usr/bin/osascript -e 'with timeout of 15 seconds' -e 'tell application "Messages" to quit' -e 'end timeout' 2>/dev/null
  sleep 3
  pkill -x Messages 2>/dev/null && sleep 2
  # not `open -g`: a background launch comes back running but deaf to AppleScript (-1712 on everything)
  /usr/bin/open -a Messages
  # wait until it answers AppleScript again
  for i in {1..15}; do
    /usr/bin/osascript -e 'with timeout of 5 seconds' -e 'tell application "Messages" to count of every chat' -e 'end timeout' >/dev/null 2>&1 && return 0
    sleep 2
  done
  return 1
}

send && exit 0
echo "imessage_send: send failed; relaunching Messages.app and retrying once" >&2
sleep 5
already_sent && { echo "imessage_send: first attempt was delivered after all; not resending" >&2; exit 0; }
relaunch || { echo "imessage_send: Messages.app did not come back after relaunch" >&2; exit 1; }
already_sent && { echo "imessage_send: first attempt was delivered after all; not resending" >&2; exit 0; }
send && { echo "imessage_send: sent on retry" >&2; exit 0; }
echo "imessage_send: retry failed too" >&2
exit 1
