#!/usr/bin/env bash
set -euo pipefail

ROOT="/workspace/steuerreport-v2-plan"
STATIC_TARGET="/workspace/steuerreport/src/tax_engine/ui/static/v2"
BACKEND_LOG="/tmp/steuerreport-v2-backend.log"
BACKEND_PID="/tmp/steuerreport-v2-backend.pid"
PROCESS_PATTERN="python3 -m uvicorn steuerreport_v2.api.app:app --host 0.0.0.0 --port 8010"

stop_backend() {
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
}

cd "$ROOT/frontend"
npm install --no-bin-links
npm run build

rm -rf "$STATIC_TARGET"
mkdir -p "$STATIC_TARGET"
cp -a "$ROOT/frontend/dist/." "$STATIC_TARGET/"

stop_backend
sleep 1

cd "$ROOT"
setsid python3 -m uvicorn steuerreport_v2.api.app:app \
  --host 0.0.0.0 \
  --port 8010 \
  > "$BACKEND_LOG" 2>&1 < /dev/null &
backend_pid=$!
echo "$backend_pid" > "$BACKEND_PID"
sleep 2
if ! ps -p "$backend_pid" >/dev/null 2>&1; then
  echo "V2 backend failed to start. Log:"
  tail -n 40 "$BACKEND_LOG"
  exit 1
fi

echo "V2 frontend: http://192.168.2.122:8000/ui/static/v2/index.html"
echo "V2 backend:  http://192.168.2.122:8010"
