#!/usr/bin/env bash
# One-command install for switchbay: prerequisites → Python deps →
# frontend build → always-on service. Idempotent; safe to re-run.
#
#   bash scripts/install.sh            # lean install (FTS-only recall)
#   bash scripts/install.sh --semantic # + light local embeddings (fastembed/ONNX, ~150 MB)
#
# Prereqs it can auto-provide: uv. Prereqs it cannot (tells you how):
# Node.js + pnpm. macOS (launchd) and Linux (systemd --user) supported.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

SEMANTIC=0
for arg in "$@"; do
  case "$arg" in
    --semantic|--with-semantic) SEMANTIC=1 ;;
    -h|--help) grep '^#' "$0" | grep -v '^#!' | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown option: $arg (try --help)"; exit 2 ;;
  esac
done

info()  { printf '\033[1;34m▸\033[0m %s\n' "$*"; }
ok()    { printf '\033[1;32m✓\033[0m %s\n' "$*"; }
warn()  { printf '\033[1;33m!\033[0m %s\n' "$*"; }
die()   { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ── uv (auto-install if missing) ─────────────────────────────────────
ensure_uv() {
  if command -v uv >/dev/null 2>&1; then ok "uv $(uv --version 2>/dev/null | awk '{print $2}')"; return; fi
  for c in "$HOME/.local/bin/uv" /opt/homebrew/bin/uv /usr/local/bin/uv; do
    [ -x "$c" ] && { export PATH="$(dirname "$c"):$PATH"; ok "uv (found at $c)"; return; }
  done
  info "uv not found — installing (https://astral.sh/uv)…"
  curl -LsSf https://astral.sh/uv/install.sh | sh || die "uv install failed; install it manually then re-run."
  export PATH="$HOME/.local/bin:$PATH"
  command -v uv >/dev/null 2>&1 || die "uv still not on PATH — reopen your shell and re-run."
  ok "uv installed"
}

# ── Node + pnpm (cannot auto-install cleanly; guide the user) ─────────
ensure_node_pnpm() {
  command -v node >/dev/null 2>&1 || die "Node.js not found. Install it (macOS: \`brew install node\`; or https://nodejs.org) and re-run."
  ok "node $(node --version)"
  if command -v pnpm >/dev/null 2>&1; then ok "pnpm $(pnpm --version)"; return; fi
  # corepack ships with Node ≥16 and can activate pnpm without a global install.
  if command -v corepack >/dev/null 2>&1; then
    info "pnpm not found — enabling via corepack…"
    corepack enable >/dev/null 2>&1 && corepack prepare pnpm@latest --activate >/dev/null 2>&1 || true
  fi
  command -v pnpm >/dev/null 2>&1 || die "pnpm not found. Install it (\`corepack enable\` or \`npm i -g pnpm\`) and re-run."
  ok "pnpm $(pnpm --version)"
}

info "switchbay install → $REPO"
ensure_uv
ensure_node_pnpm

# kuzu (CE graph) has wheels only through Python 3.13. A Mac whose
# `python3` is 3.14 makes bare `uv venv` / `uv sync` pick 3.14 and
# CE setup then fails to install kuzu. Pin 3.13 first.
CE_PY="${SWITCHBAY_CE_PYTHON:-3.13}"
info "Ensuring Python ${CE_PY} (kuzu / curiosity-engine)…"
uv python install "$CE_PY" || warn "uv python install ${CE_PY} failed — continuing if it is already present"
if [ -x "$REPO/.venv/bin/python" ] || [ -x "$REPO/.venv/bin/python3" ]; then
  :
else
  uv python pin "$CE_PY" || true
fi
export UV_PYTHON="$CE_PY"

info "Python deps (uv sync)…"
uv sync
if [ "$SEMANTIC" = "1" ]; then
  info "Local semantic embeddings (fastembed / ONNX, ~150 MB)…"
  uv sync --group semantic
  ok "semantic embeddings enabled (fastembed)"
else
  warn "Skipping local semantic embeddings — recall runs FTS-only."
  warn "Add them later with: make sync-semantic   (or bash scripts/install.sh --semantic)"
fi

info "Frontend deps + build…"
pnpm --dir frontend install
pnpm --dir frontend run build

info "Curiosity-engine skill (global)…"
if [ -d "$HOME/.agents/skills/curiosity-engine/scripts" ] || [ -d "$HOME/.claude/skills/curiosity-engine/scripts" ]; then
  ok "curiosity-engine skill already installed"
else
  if command -v npx >/dev/null 2>&1; then
    # -y on *skills* is required — without it a headless install hangs.
    npx -y skills add -g -y benjsmith/curiosity-engine \
      && ok "curiosity-engine skill installed" \
      || warn "skill install failed — run: npx skills add -g -y benjsmith/curiosity-engine"
  else
    warn "npx not found — install Node, then: npx skills add -g -y benjsmith/curiosity-engine"
  fi
fi

info "Registering the always-on service…"
PYTHONPATH="$REPO/src" uv run --no-sync python -m switchbay service install

ok "Installed. Open http://127.0.0.1:8765 and install it as an app (dock icon + standalone window)."
echo "   Manage it with: make status | make stop | make restart | make uninstall-service"
