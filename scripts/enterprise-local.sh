#!/bin/bash
# Flip this git checkout between open (consumer) and enterprise profile
# without an MSI/PKG. Overlay is repo-root admin.json (gitignored).
set -euo pipefail
ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)
ADMIN="$ROOT/admin.json"
MODE=${1:-on}

if [ "$MODE" = "on" ]; then
  cat > "$ADMIN" <<'JSON'
{
  "profile": "enterprise",
  "allow_profile_override": true,
  "copilot": { "host": "github.com", "lock_host": false },
  "features": {
    "hf_model_download": true,
    "install_skills_npx": true,
    "interactive_terminal": true,
    "agent_run_command": true,
    "in_app_update": false,
    "ce_auto_setup": false,
    "uv_python_install": false
  }
}
JSON
  echo "wrote $ADMIN (enterprise + HF downloads on for local-model testing)"
else
  rm -f "$ADMIN"
  echo "removed $ADMIN (open profile)"
fi

if command -v launchctl >/dev/null && [ -f "$HOME/Library/LaunchAgents/com.switchbay.daemon.plist" ]; then
  PYTHONPATH="$ROOT/src" "$ROOT/.venv/bin/python" -m switchbay service restart
  echo "restarted launchd agent. Open http://127.0.0.1:8765"
else
  echo "restart the daemon yourself: make restart"
fi
