# Use `make ...` for everything Python — never `uv sync` / `uv run` directly.
#
# We don't install switchbay into the venv (see [tool.uv] package = false in
# pyproject.toml). Instead we set PYTHONPATH=src and invoke `python -m
# switchbay`. This sidesteps the macOS UF_HIDDEN issue that breaks editable
# `.pth` files inside `.venv/`.

.PHONY: install sync sync-semantic sync-semantic-torch sync-frontend \
        dev-daemon dev-frontend build-frontend install-service \
        uninstall-service start stop restart status refresh test test-py check e2e \
        enterprise-local open-local enterprise-bake vscode-compile vsix

PYDIR := $(CURDIR)/src

# One-command install for a fresh clone: prerequisites (auto-installs uv;
# checks node/pnpm) → Python deps → frontend build → always-on service.
# Add SEMANTIC=1 to also pull the light fastembed embeddings (~150 MB).
# Add ENTERPRISE_USER=1 for a tester enterprise overlay (repo admin.json, no sudo).
install:
	bash scripts/install.sh $(if $(SEMANTIC),--semantic,) $(if $(ENTERPRISE_USER),--enterprise-user,)

sync:
	uv sync --locked

# Opt-in local semantic embeddings (Tier-3 recall), LIGHT path: fastembed
# (ONNX, no PyTorch), ~150 MB. Recall fail-softs to FTS-only without it.
sync-semantic:
	uv sync --locked --group semantic

# Heavyweight semantic path: sentence-transformers + PyTorch (~450 MB).
# Only if you need byte-exact interop with a curiosity-engine vault index.
sync-semantic-torch:
	uv sync --locked --group semantic-torch

sync-frontend:
	pnpm --dir frontend install --frozen-lockfile

# Hermetic Python unit suite (tests/unit). Syncs the dev group first so
# pytest is available, then runs without re-resolving. tests/integration
# is the live-daemon round-trip — run that one by hand.
test test-py:
	uv sync --locked --group dev
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

# Switch Bay VS (extensions/switchbay-vs). Compiles the extension host;
# does not start the PWA daemon.
vscode-compile:
	pnpm --dir extensions/switchbay-vs install --frozen-lockfile
	pnpm --dir extensions/switchbay-vs run test
	pnpm --dir frontend run build:webview

# Marketplace / sideload VSIX. Graph assets are gitignored, so we stage a
# copy outside the git worktree (vsce otherwise skips them).
VSIX_VERSION := $(shell node -p "require('./extensions/switchbay-vs/package.json').version")
VSIX_STAGING := /tmp/switchbay-vs-pack

vsix: vscode-compile
	@test -f extensions/switchbay-vs/media/icon.png || (echo "missing media/icon.png"; exit 1)
	@test -f extensions/switchbay-vs/media/graph/webview-graph.html || \
		(echo "missing graph webview — vscode-compile should have built it"; exit 1)
	rm -rf $(VSIX_STAGING)
	mkdir -p $(VSIX_STAGING)/out $(VSIX_STAGING)/static/mars-hopper
	rsync -a --exclude '*.map' extensions/switchbay-vs/out/ $(VSIX_STAGING)/out/
	rsync -a extensions/switchbay-vs/media/ $(VSIX_STAGING)/media/
	rsync -a extensions/switchbay-vs/agents/ $(VSIX_STAGING)/agents/
	rsync -a extensions/switchbay-vs/scripts/ $(VSIX_STAGING)/scripts/
	cp extensions/switchbay-vs/package.json extensions/switchbay-vs/README.md \
		extensions/switchbay-vs/.vscodeignore $(VSIX_STAGING)/
	cp LICENSE $(VSIX_STAGING)/LICENSE
	cp static/mars-hopper/index.html static/mars-hopper/style.css static/mars-hopper/game.js \
		$(VSIX_STAGING)/static/mars-hopper/
	mkdir -p dist
	cd $(VSIX_STAGING) && $(CURDIR)/extensions/switchbay-vs/node_modules/.bin/vsce package \
		--no-dependencies \
		--out $(CURDIR)/dist/switchbay-vs-$(VSIX_VERSION).vsix
	@echo "VSIX: dist/switchbay-vs-$(VSIX_VERSION).vsix"
	@unzip -l dist/switchbay-vs-$(VSIX_VERSION).vsix | grep -E \
		'out/extension.js|media/graph/webview-graph.html|static/mars-hopper/index.html|media/icon.png|LICENSE|README.md'

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
# ENTERPRISE_USER=1 stamps <repo>/admin.json (tester enterprise, no sudo).
ENTERPRISE_USER ?=
install-service: build-frontend
	PYTHONPATH=$(PYDIR) uv run --no-sync python -m switchbay service install $(if $(ENTERPRISE_USER),--enterprise-user,)
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

# Local enterprise-mode test on a git checkout (no MSI/PKG). Writes
# gitignored admin.json (HF downloads on so you can pull a small local
# model), restarts the per-user service. `make open-local` reverts.
enterprise-local:
	bash scripts/enterprise-local.sh on
open-local:
	bash scripts/enterprise-local.sh off

# Company bake machine: stamp policy + assemble Intune/Jamf layout.
# PAYLOAD= path to unzipped CI zip/tar. Then read $(or dist/bake)/NEXT.txt
# and sign. Example:
#   make enterprise-bake PAYLOAD=dist/switchbay-enterprise-darwin-arm64 \
#        COPILOT_HOST=github.example.com
PAYLOAD ?=
COPILOT_HOST ?= github.com
IN_APP_UPDATE ?=
UPDATE_REPO ?=
enterprise-bake:
	@test -n "$(PAYLOAD)" || (echo "set PAYLOAD= to the unzipped CI tree or archive"; exit 1)
	PYTHONPATH=$(PYDIR) uv run --no-sync python scripts/bake_enterprise.py \
		--payload $(PAYLOAD) --copilot-host $(COPILOT_HOST) \
		--out dist/bake $(if $(ALLOW_HF),--allow-hf,) \
		$(if $(IN_APP_UPDATE),--in-app-update,) \
		$(if $(UPDATE_REPO),--update-repo $(UPDATE_REPO),) \
		$(if $(VENDOR_CE),--vendor-ce $(VENDOR_CE),)
