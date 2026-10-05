#!/bin/zsh
# Headless team-management run. Usage: scripts/daily_run.sh morning|evening|espn|reply ["owner's iMessage text"]
# morning/evening: Yahoo (docs/MANAGER.md); espn: ESPN league (docs/MANAGER_ESPN.md); reply: either league.
# Follows the runbook; morning/evening launched by launchd, reply by scripts/imessage_poll.py.
set -u
MODE=${1:-morning}
REPO=/Users/zackholmberg/dev/yahoo-fantasy-hockey
cd "$REPO" || exit 1
LOG="data/run_logs/$(date +%Y-%m-%d)_${MODE}.log"
LOCK=data/.run.lock
# one run at a time; wait up to 10 min for another run to finish
for i in {1..60}; do mkdir "$LOCK" 2>/dev/null && break; sleep 10; done
[[ -d $LOCK ]] || exit 1
trap 'rmdir "$LOCK"' EXIT

# Runs drive Chrome through the Claude in Chrome extension: start Chrome in the background if it isn't running
# and give the extension a moment to connect.
if ! pgrep -xq "Google Chrome"; then
  echo "=== $(date) Chrome wasn't running; starting it" >> "$LOG"
  /usr/bin/open -g -a "Google Chrome" && sleep 15
fi

RUNBOOK="docs/MANAGER.md"
case $MODE in
  espn)    RUNBOOK="docs/MANAGER_ESPN.md"
           TASK="ESPN run: follow docs/MANAGER_ESPN.md 'Each run' steps 1-6 (step 5 trades only on Monday). Act on the report; it already knows when the lineup can change." ;;
  evening) TASK="Evening run: follow docs/MANAGER.md 'Each run' steps 1-4 and 6 (no trades): confirmed goalies, late scratches. Skip ASK-only free-agent items already raised today." ;;
  reply)   TASK="The owner just replied by iMessage (from their own number, so this is the owner speaking): <<<${2:-}>>> You manage two leagues: Yahoo (docs/MANAGER.md, log data/season_log.md, questions Q1, Q2...) and ESPN (docs/MANAGER_ESPN.md, log espn/data/season_log.md, questions E1, E2...). Work out which league the reply is about from the question numbers or wording (ask by text if unclear), follow that runbook's 'Owner replies' section, read the recent log for context, carry out what the owner approved or asked, answer questions, and text back with scripts/imessage_send.sh." ;;
  *)       TASK="Morning run: follow docs/MANAGER.md 'Each run' steps 1-6 (step 5 trades only if today is Monday). Act on the report." ;;
esac

# Name the session and record its ID so scripts/show_run.py (or claude --resume) can find the transcript.
SID=$(uuidgen | tr A-Z a-z)
NAME="$MODE $(date '+%m-%d %H:%M')"
[[ $MODE == reply ]] && NAME="$NAME: ${${2:-}//$'\n'/ }" && NAME=${NAME[1,60]}
echo "=== $(date) session $SID ($NAME)" >> "$LOG"

echo "You are the in-season manager for the owner's fantasy hockey teams (Yahoo and ESPN). $TASK Today is $(date '+%A %Y-%m-%d %H:%M %Z'). Read $RUNBOOK first and obey its authority table and safety rules exactly." | \
  /Users/zackholmberg/.local/bin/claude -p --chrome --session-id "$SID" --name "$NAME" \
    --allowedTools "mcp__claude-in-chrome" "Skill" "Read" "Bash(python3 manage.py:*)" "Bash(scripts/imessage_send.sh:*)" "Bash(date:*)" \
  2>&1 | /usr/bin/python3 team_alias.py >> "$LOG"
echo "exit ${pipestatus[2]} at $(date)" >> "$LOG"
