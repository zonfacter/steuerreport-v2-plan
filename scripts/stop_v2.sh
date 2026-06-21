#!/usr/bin/env bash
set -euo pipefail

BACKEND_PID="/tmp/steuerreport-v2-backend.pid"
PROCESS_PATTERN="python3 -m uvicorn steuerreport_v2.api.app:app --host 0.0.0.0 --port 8010"

if [ -f "$BACKEND_PID" ]; then
  old_pid="$(cat "$BACKEND_PID")"
  if [ -n "$old_pid" ] && ps -p "$old_pid" >/dev/null 2>&1; then
    kill "$old_pid" 2>/dev/null || true
  fi
  rm -f "$BACKEND_PID"
fi

ps -eo pid=,args= | awk -v pat="$PROCESS_PATTERN" -v self="$$" '
  index($0, pat) && $1 != self && index($0, "awk -v pat") == 0 {print $1}
' | while read -r pid; do
  kill "$pid" 2>/dev/null || true
done

echo "Steuerreport V2 backend stopped."
