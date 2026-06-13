#!/usr/bin/env bash
#
# t-525 (ini-026 T4): rising-edge macOS notification for autopilot
# anomalies with severity high|urgent.
#
# Usage:
#   scripts/autopilot-notify.sh fire <type> <severity> <message>
#   scripts/autopilot-notify.sh clear <type>
#
# `fire` notifies ONCE per continuous anomaly episode: the first fire
# for a type records it under "notified" in .autopilot-state.json and
# displays the notification; repeat fires while the anomaly persists
# are silent. `clear` (call when the anomaly is absent this tick)
# re-arms the type so the next trip fires again — rising-edge dedup
# per the design (§Allow-listed actions item 9).
#
# Severity low|moderate exits 0 silently — notifications are reserved
# for high|urgent per the t-524 protocol table.
#
# Env:
#   FORGE_ROOT            project root (default: script's ../)
#   AUTOPILOT_NOTIFY_CMD  notifier executable (default: osascript;
#                         tests inject a recorder here)

set -euo pipefail

MODE="${1:?fire|clear}"
TYPE="${2:?anomaly type (e.g. A9)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
FORGE_ROOT="${FORGE_ROOT:-$(cd "$SCRIPT_DIR/.." && pwd)}"
STATE="$FORGE_ROOT/.autopilot-state.json"
NOTIFY_CMD="${AUTOPILOT_NOTIFY_CMD:-osascript}"

case "$MODE" in
fire)
  SEVERITY="${3:?severity}"
  MESSAGE="${4:?message}"
  case "$SEVERITY" in
    high|urgent) ;;
    low|moderate) exit 0 ;;
    *) echo "autopilot-notify: invalid severity '$SEVERITY'" >&2; exit 2 ;;
  esac
  # Atomically test-and-set the notified flag. Exit 3 from python =
  # already notified this episode → suppress.
  set +e
  python3 - "$STATE" "$TYPE" <<'PYEOF'
import json, sys
from pathlib import Path
path, typ = Path(sys.argv[1]), sys.argv[2]
try:
    data = json.loads(path.read_text())
except (OSError, ValueError):
    data = {}
notified = data.setdefault("notified", {})
if notified.get(typ):
    sys.exit(3)
notified[typ] = True
path.write_text(json.dumps(data, indent=2) + "\n")
PYEOF
  rc=$?
  set -e
  if (( rc == 3 )); then
    exit 0          # continued state — no re-fire
  elif (( rc != 0 )); then
    exit "$rc"
  fi
  "$NOTIFY_CMD" -e "display notification \"$MESSAGE\" with title \"Forge autopilot · $TYPE\"" || true
  ;;
clear)
  python3 - "$STATE" "$TYPE" <<'PYEOF'
import json, sys
from pathlib import Path
path, typ = Path(sys.argv[1]), sys.argv[2]
try:
    data = json.loads(path.read_text())
except (OSError, ValueError):
    sys.exit(0)
if data.get("notified", {}).pop(typ, None) is not None:
    path.write_text(json.dumps(data, indent=2) + "\n")
PYEOF
  ;;
*)
  echo "autopilot-notify: unknown mode '$MODE' (fire|clear)" >&2
  exit 2
  ;;
esac
exit 0
