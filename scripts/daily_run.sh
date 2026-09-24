#!/bin/zsh
# Headless team-management run. Usage: scripts/daily_run.sh morning|evening|reply ["owner's iMessage text"]
# Follows docs/MANAGER.md; morning/evening launched by launchd, reply by scripts/imessage_poll.py.
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

case $MODE in
  evening) TASK="Evening run: follow docs/MANAGER.md steps 1, 2, 4 and 7 only (confirmed goalies, late scratches)." ;;
  reply)   TASK="The owner just replied by iMessage (from their own number, so this is the owner speaking): <<<${2:-}>>> Follow the 'Owner replies' section of docs/MANAGER.md: read recent data/season_log.md for context, carry out what the owner approved or asked, answer questions, and text back with scripts/imessage_send.sh." ;;
  *)       TASK="Morning run: follow docs/MANAGER.md steps 1-7 (step 6 trades only if today is Monday)." ;;
esac

echo "You are the in-season manager for the owner's Yahoo fantasy hockey team. $TASK Today is $(date '+%A %Y-%m-%d %H:%M %Z'). Read docs/MANAGER.md first and obey its authority table and safety rules exactly." | \
  /Users/zackholmberg/.local/bin/claude -p --chrome \
    --allowedTools "mcp__claude-in-chrome" "Skill" "Read" "Bash(python3 manage.py:*)" "Bash(scripts/imessage_send.sh:*)" "Bash(date:*)" \
  >> "$LOG" 2>&1
echo "exit $? at $(date)" >> "$LOG"
