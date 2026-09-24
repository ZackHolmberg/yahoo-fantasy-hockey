#!/bin/zsh
# Text the owner via Messages.app. Usage: scripts/imessage_send.sh "message"
cd /Users/zackholmberg/dev/yahoo-fantasy-hockey || exit 1
HANDLE=$(/usr/bin/python3 -c 'import json;print(json.load(open("data/imessage.json"))["handle"])')
PREFIX=$(/usr/bin/python3 -c 'import json;print(json.load(open("data/imessage.json"))["prefix"],end="")')
/usr/bin/osascript - "$HANDLE" "$PREFIX$1" <<'OSA'
on run argv
  tell application "Messages"
    set svc to 1st account whose service type = iMessage
    send (item 2 of argv) to participant (item 1 of argv) of svc
  end tell
end run
OSA
