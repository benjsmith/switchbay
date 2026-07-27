#!/usr/bin/env bash
# Refresh the local Switch Bay stack for iterative dev against the
# installed PWA (http://127.0.0.1:8765).
#
#   make refresh              # restart daemon; open PWA auto-reloads
#   make refresh BUILD=1      # also rebuild frontend/dist first
#   scripts/dev-refresh.sh --build
#
# The open PWA does NOT need to be quit: frontend/src/devReload.ts
# polls /api/health and reloads when boot_id / frontend_mtime change.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Makefile may pass BUILD=1 in the environment; CLI --build also sets it.
# Capture env first so a local flag var doesn't shadow it.
WANT_BUILD=0
if [[ "${BUILD:-0}" == "1" ]]; then
  WANT_BUILD=1
fi
WAIT_S=45
PORT=8765
for arg in "$@"; do
  case "$arg" in
    --build|-b) WANT_BUILD=1 ;;
    --wait=*) WAIT_S="${arg#--wait=}" ;;
    --help|-h)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "unknown arg: $arg (try --build)" >&2
      exit 2
      ;;
  esac
done

log() { printf '· %s\n' "$*"; }

if [[ "$WANT_BUILD" == "1" ]]; then
  log "building frontend/dist…"
  pnpm --dir frontend run build
else
  log "skipping frontend build (pass --build / BUILD=1 to rebuild dist)"
fi

# Prefer the always-on service restart. If launchd/systemd doesn't own
# a process (common when the daemon was started via `make dev-daemon`
# or a one-shot nohup), fall back to killing whatever holds :8765 and
# starting the service (or a detached serve).
restart_daemon() {
  log "restarting daemon…"
  if PYTHONPATH=src uv run --no-sync python -m switchbay service restart 2>/tmp/sy-refresh-restart.err; then
    return 0
  fi
  log "service restart failed ($(tr '\n' ' ' </tmp/sy-refresh-restart.err | head -c 160)) — falling back"

  # Free the port: kill listeners on 8765 (daemon only; leave vite alone).
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -tiTCP:${PORT} -sTCP:LISTEN 2>/dev/null || true)"
    if [[ -n "${pids}" ]]; then
      log "killing listener(s) on :${PORT}: ${pids}"
      # shellcheck disable=SC2086
      kill ${pids} 2>/dev/null || true
      sleep 0.5
      # shellcheck disable=SC2086
      kill -9 ${pids} 2>/dev/null || true
    fi
  fi

  # Try service start (launchd agent installed).
  if PYTHONPATH=src uv run --no-sync python -m switchbay service start 2>/tmp/sy-refresh-start.err; then
    return 0
  fi

  log "service start failed — launching detached serve"
  # Last resort: same shape as a manual nohup daemon. Log to the
  # standard macOS path when present, else /tmp.
  local logfile="${HOME}/Library/Logs/switchbay-daemon.log"
  mkdir -p "$(dirname "$logfile")" 2>/dev/null || logfile="/tmp/sy-daemon.log"
  nohup env PYTHONPATH=src PYTHONUNBUFFERED=1 \
    uv run --no-sync python -m switchbay serve --workspace "${WORKSPACE:-$ROOT}" \
    >>"$logfile" 2>&1 &
  log "detached serve pid $! (log: $logfile)"
}

restart_daemon

log "waiting up to ${WAIT_S}s for http://127.0.0.1:${PORT}/api/health …"
deadline=$(( $(date +%s) + WAIT_S ))
boot_id=""
while (( $(date +%s) < deadline )); do
  if body="$(curl -fsS --max-time 1 "http://127.0.0.1:${PORT}/api/health" 2>/dev/null)"; then
    boot_id="$(printf '%s' "$body" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("boot_id",""))' 2>/dev/null || true)"
    if [[ -n "$boot_id" ]]; then
      log "healthy  boot_id=${boot_id:0:8}…  ${body}"
      log "open PWA/tab will auto-reload within ~4s (leave it open)"
      exit 0
    fi
  fi
  sleep 0.4
done

echo "daemon did not become healthy on :${PORT} within ${WAIT_S}s" >&2
echo "check: make status   and   tail -f ~/Library/Logs/switchbay-daemon.log" >&2
exit 1
