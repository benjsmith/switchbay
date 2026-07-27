# Use `make ...` for everything Python — never `uv sync` / `uv run` directly.
#
# We don't install switchbay into the venv (see [tool.uv] package = false in
# pyproject.toml). Instead we set PYTHONPATH=src and invoke `python -m
# switchbay`. This sidesteps the macOS UF_HIDDEN issue that breaks editable
# `.pth` files inside `.venv/`.

.PHONY: install sync sync-semantic sync-semantic-torch sync-frontend \
        dev-daemon dev-frontend build-frontend install-service \
        uninstall-service start stop restart status refresh test test-py check e2e

PYDIR := $(CURDIR)/src

# One-command install for a fresh clone: prerequisites (auto-installs uv;
# checks node/pnpm) → Python deps → frontend build → always-on service.
# Add SEMANTIC=1 to also pull the light fastembed embeddings (~150 MB).
install:
	bash scripts/install.sh $(if $(SEMANTIC),--semantic,)

sync:
	uv sync

# Opt-in local semantic embeddings (Tier-3 recall), LIGHT path: fastembed
# (ONNX, no PyTorch), ~150 MB. Recall fail-softs to FTS-only without it.
sync-semantic:
	uv sync --group semantic

# Heavyweight semantic path: sentence-transformers + PyTorch (~450 MB).
# Only if you need byte-exact interop with a curiosity-engine vault index.
sync-semantic-torch:
	uv sync --group semantic-torch

sync-frontend:
	pnpm --dir frontend install

# Hermetic Python unit suite (tests/unit). Syncs the dev group first so
# pytest is available, then runs without re-resolving. tests/integration
# is the live-daemon round-trip — run that one by hand.
test test-py:
	uv sync --group dev
	uv run --no-sync pytest

# Full pre-commit gate: unit tests + Python import smoke + frontend
# typecheck/build. Mirrors CI.
check: test
	PYTHONPATH=$(PYDIR) uv run --no-sync python -c "import switchbay.daemon"
	pnpm --dir frontend run build

# Browser smoke (Playwright). Assumes the dev servers are already live
# (daemon :8765 + vite :5173 — see README). Not part of `check`/CI
# because driving the full daemon headlessly is environment-sensitive.
e2e:
	pnpm --dir frontend exec playwright test

dev-daemon: sync
	PYTHONPATH=$(PYDIR) uv run --no-sync python -m switchbay serve --workspace $${WORKSPACE:-$$PWD}

dev-frontend:
	pnpm --dir frontend run dev

# Production build: the daemon serves frontend/dist at / (so the PWA
# installs from the always-on daemon, no vite). Run this before
# install-service and after frontend changes.
build-frontend:
	pnpm --dir frontend run build

# Always-on daemon as a per-user OS service — launchd (macOS) /
# systemd --user (Linux) / Scheduled Task (Windows). Cross-platform impl
# lives in src/switchbay/service.py; these targets are mac/Linux make
# conveniences. On Windows run `python -m switchbay service <action>`.
# install builds the frontend first so the daemon has something to serve.
install-service: build-frontend
	PYTHONPATH=$(PYDIR) uv run --no-sync python -m switchbay service install
uninstall-service:
	PYTHONPATH=$(PYDIR) uv run --no-sync python -m switchbay service uninstall
start:
	PYTHONPATH=$(PYDIR) uv run --no-sync python -m switchbay service start
stop:
	PYTHONPATH=$(PYDIR) uv run --no-sync python -m switchbay service stop
restart:
	PYTHONPATH=$(PYDIR) uv run --no-sync python -m switchbay service restart
status:
	PYTHONPATH=$(PYDIR) uv run --no-sync python -m switchbay service status

# Dev loop against the installed PWA: restart the daemon (and
# optionally rebuild frontend/dist). The open PWA/tab auto-reloads
# via /api/health — no quit/reopen. Examples:
#   make refresh              # daemon only
#   make refresh BUILD=1      # rebuild UI + restart daemon
refresh:
	BUILD=$(if $(BUILD),$(BUILD),0) bash scripts/dev-refresh.sh $(if $(filter 1,$(BUILD)),--build,)
