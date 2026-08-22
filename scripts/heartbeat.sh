#!/bin/bash
# heartbeat.sh - the external dead-man's switch ping (Pattern 10, the external half).
#
# The daily guard calls this at the END of a clean run. The URL points at an external check
# (healthchecks.io, cronitor, or any equivalent) whose grace period is a little over a day: if no
# ping arrives, the service notifies the operator. That is the only signal that works when the
# host is asleep, the scheduler has stalled, or the fleet died on usage credits - a dead run
# cannot ping, which is the point.
#
#   bash scripts/heartbeat.sh            # ping (exit 0 even if unconfigured - the guard must not fail on this)
#   bash scripts/heartbeat.sh --fail     # ping the /fail endpoint: the guard ran but found something critical
#   bash scripts/heartbeat.sh --status   # print configuration state, no ping
#
# Configuration: put the ping URL (and nothing else) in config/heartbeat_url.txt. That file is
# gitignored - it is a capability URL, and anyone holding it can silence your alarm. Never paste
# it into a prompt, a state file, or a log line.
set -u
CONF="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/config/heartbeat_url.txt"
MODE="${1:-ping}"
if [ ! -s "$CONF" ]; then
  echo "heartbeat: NOT CONFIGURED - create $CONF containing the ping URL"; exit 0
fi
URL="$(tr -d '[:space:]' < "$CONF")"
case "$MODE" in
  --status) echo "heartbeat: configured ($(echo "$URL" | sed -E 's#(https?://[^/]+/).*#\1...#'))"; exit 0 ;;
  --fail)   URL="${URL%/}/fail" ;;
esac
if out=$(curl -fsS -m 15 --retry 3 --retry-delay 5 -o /dev/null -w '%{http_code}' "$URL" 2>&1); then
  echo "heartbeat: OK ($MODE, http $out, $(date -u +%Y-%m-%dT%H:%M:%SZ))"; exit 0
else
  echo "heartbeat: PING FAILED ($MODE): $out"; exit 1
fi
