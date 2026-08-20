# Switch Bay

<img width="3437" height="1398" alt="image" src="https://github.com/user-attachments/assets/d1abbde7-650a-4b02-b318-426024709220" />

> **An agentic second brain you grow.** Feed it your notes, docs, and
> sources; capable agents curate them into expert knowledge graphs that
> compound — richer every session, owned and guided by you.
> **Route it. Grow it. Use it.**

Switch Bay turns a folder of raw material — notes, documents, sources,
tasks — into a private, compounding **knowledge graph**, and gives you a
cockpit where AI agents work over it: chat grounded in what you know,
curate captured material into linked wiki pages, fan out parallel agents,
and render rich answers as documents. It runs **entirely on your
machine**, against whatever models you choose, and nothing leaves unless
you send it.

- **Local & private** — two processes and your files. No cloud, no
  accounts; your data and API keys stay on your machine.
- **Bring your own models** — hosted APIs (Anthropic, xAI Grok, OpenAI,
  Gemini, Meta Muse Spark), subscription coding CLIs (Claude Code, Grok
  Build, Muse Code, Codex, Copilot), or fully-local models (llama.cpp /
  Ollama). Mix them per task with a model ladder.
- **Knowledge that compounds** — capture → curate → graph. Every session
  leaves the graph richer, so the next one starts smarter. Agents propose
  wiki edits; a stronger reviewer (and you) keep them honest.
- **Two cockpits** — **Power** mode (3-column: browser · tabs · rail) and
  **Zen** mode (think *at* the graph). Same data, your choice.
- **Custom tabs** — describe the view you want and an agent builds it
  just-in-time over your own data. Pin the keepers (globally or per
  workspace); throw the rest away.

New here? Read **[`docs/concepts-and-data-flow.md`](docs/concepts-and-data-flow.md)**
— how Switch Bay is put together in one read: the core vocabulary
(**Workspace → Thread → Run → Turn**), the runtime shape, and the data
flows behind the things you do most. Provider coverage (what's
first-class vs preview, including Muse Code) is
**[`docs/providers.md`](docs/providers.md)**. This **enterprise** branch
defaults to GitHub Copilot + local models and an admin-only policy
file — see **[`docs/enterprise.md`](docs/enterprise.md)**.

A workspace is any folder with a **curiosity-engine**-shaped layout
(`vault/` raw sources + `wiki/` docs & graph); Switch Bay degrades
gracefully on folders that don't have one yet.

## Install (one command)

On a fresh clone, this checks prerequisites (auto-installs `uv`; tells
you how to get Node + pnpm if missing), installs deps, builds the
frontend, and registers the always-on service:

```sh
make install                 # lean install — recall runs FTS-only
make install SEMANTIC=1      # + local semantic embeddings (fastembed/ONNX, ~150 MB)
```

Then open `http://127.0.0.1:8765` and install it as an app. You can add
local semantic embeddings later with `make sync-semantic`.

> **Prerequisites:** `git`, **Node.js + pnpm** (the installer guides you
> if they're missing), and `uv` (auto-installed). Python ≥3.11 is
> provisioned by `uv`. The base install is ~50 MB of Python deps;
> `SEMANTIC=1` adds ~150 MB (fastembed, no PyTorch). Semantic recall is
> fail-soft — without it, `recall_rail` degrades to full-text search
> only. For byte-exact interop with a curiosity-engine vault index you
> can instead use the PyTorch backend: `make sync-semantic-torch`.

### macOS permission prompts (expected)

The daemon is a `python3.13` process (the venv interpreter `uv`
provisions). On first install / first start, macOS may show one or
both of these sheets **from python3.13**, not from an app named
Switch Bay. That is the same process. **Allow** is the intended
choice for a normal install.

| Prompt | What it is for | If you click Don’t Allow |
|--------|----------------|--------------------------|
| **“…would like to access data from other apps.”** | Looking under `~/Library/Containers/` for Hugging Face / MLX weight caches other Mac apps already downloaded (so Settings can offer **Use this** instead of fetching the same files again). Switch Bay does not read those apps’ documents or accounts. | Local models still work. You just won’t see weights that only live in another app’s sandbox; install or point at a snapshot yourself. |
| **“…wants to use the keychain”** / **“…wants to access keychain”** | Storing provider API keys (and comms-stream secrets) in the macOS Keychain via `keyring`, service `switchbay`. Keys are not written as plaintext in config files. The first Settings → Providers key save, or a daemon boot that checks the keychain, can trigger this. | You can still run the app, but saving an API key in Settings will fail (`OS keychain unavailable`) until you Allow. |

These can also appear later (first Key save, first local-model scan).
The process name stays `python3.13` because launchd starts
`.venv/bin/python` directly.

## Run (dev)

One-time install:

```sh
make sync           # uv sync (base Python deps; add `make sync-semantic` for embeddings)
make sync-frontend  # pnpm install in frontend/
```

Two processes. In one terminal:

```sh
WORKSPACE=/path/to/workspace make dev-daemon
```

In another:

```sh
make dev-frontend
```

Then open the URL vite prints (default `http://localhost:5173`). Vite
proxies `/api` and `/ws` to the daemon on `:8765`.

## Test

```sh
make test    # hermetic unit suite (tests/unit) — pytest, no daemon needed
make check   # unit tests + daemon import smoke + frontend typecheck/build
make e2e     # Playwright browser smoke (needs the dev servers running)
```

CI (`.github/workflows/ci.yml`) runs the unit suite + import smoke and
the frontend build on every push/PR. The live-daemon round-trip in
`tests/integration/` is run by hand (it needs a running daemon + a real
workspace).

## Install as an app

For everyday use, run it as an installable PWA over an always-on local
daemon:

```sh
make install-service   # builds the frontend + registers a launchd agent
```

The daemon then serves the built app at `http://127.0.0.1:8765`; open it
and install it (dock icon + standalone window). Closing the window does
**not** stop work — runs live in the daemon. `make stop` / `make restart`
/ `make status` manage the service; `make uninstall-service` removes it.
On macOS, the first start may show the python3.13 permission sheets
documented [above](#macos-permission-prompts-expected).

### Iterating without quitting the PWA

While developing against the dock app, keep the window open and run:

```sh
make refresh              # restart daemon; open PWA auto-reloads
make refresh BUILD=1      # rebuild frontend/dist, then restart
```

The client polls `GET /api/health` on loopback and reloads when the
daemon’s `boot_id` or the built `frontend/dist` mtime changes — so you
don’t need to quit and reopen the PWA after each restart.

> **Why no `switchbay` console script?** uv-managed venvs on macOS get
> the `UF_HIDDEN` flag re-applied to their files asynchronously
> (LaunchServices / Spotlight). Python ≥3.13's `site.py` skips hidden
> `.pth` files, breaking editable installs racily. We invoke via
> `python -m switchbay` with `PYTHONPATH=src` instead — see
> `[tool.uv] package = false` in `pyproject.toml`.

## More

- **[`docs/concepts-and-data-flow.md`](docs/concepts-and-data-flow.md)** — the map: concepts + data flows.
- **[`docs/known-issues.md`](docs/known-issues.md)** — rough edges + deliberate deferrals in this release.
- **[`docs/THIRD-PARTY-NOTICES.md`](docs/THIRD-PARTY-NOTICES.md)** — third-party attributions.
- **[`docs/license-risk-report.md`](docs/license-risk-report.md)** — dependency-license review.
- **[`CLAUDE.md`](CLAUDE.md)** — orientation for AI coding sessions.
