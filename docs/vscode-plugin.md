# Switch Bay as a VS Code plugin (experiment)

Branch: `exp/vscode-plugin`. Dual product: the PWA on `main` stays.
This document is the tracked design for the experiment.

## Hypothesis

The product people actually want is the knowledge-graph workbench
(Curiosity Engine, tools, Graph/Atlas, wiki browser, project overview,
HTML artifacts, multi-agent DAG). The rest of the PWA is chrome VS Code
already owns.

**Constraint:** no always-on Python daemon. No `aiohttp`, no `:8765`, no
launchd, no PWA in the loop. The daemon exists today because the UI is a
**browser**. VS Code is not a browser.

Python remains as **on-demand workers** (stdio MCP, CE CLI, a run-scoped
orchestration child). Closing VS Code stops work.

## Keep / drop / farm-out

Keep: CE CLI, wiki tools via MCP, Auto orchestration as a run-scoped
worker, Graph/Atlas webview, wiki tree, project overview, Agent
Dashboard, HTML artifact custom editors, wiki markdown preview, Mars
Hopper via `/thrusters`.

Drop: Editor tab, DuckDB-wasm, Univer sheet, Vega plot tab, Settings →
providers, rail threads, file browser, terminal tab.

Extract: Sketch → companion VSIX `extensions/switchbay-sketch/`.

Farm out: window chrome, Explorer, Chat sessions, Copilot sign-in
(`vscode.lm`).

## Architecture

```
VS Code
  activity bar: wiki tree · projects · agent dashboard
  editors: native md · wiki preview · graph/atlas · HTML · hopper
  chat: @switchbay + /thrusters /curate /plot /deck /sketch
  vscode.lm  (Copilot models)
       │ stdio MCP                    │ subprocess
       ▼                              ▼
  python -m switchbay.mcp_server    curiosity-engine scripts
  CSWY_PROFILE=vscode               viewer.sh / sweep.py / …
```

Hard rules:

- Plugin path never imports `aiohttp`.
- Webviews never `fetch("http://127.0.0.1:8765/...")`.
- Tools that still call `_daemon_json` / `/api/*` are out of the plugin
  allowlist (`switchbay.plugin_tools`).

## Interaction

- Graph node **click** → open the `.md` in a normal VS Code tab.
- Graph node **right-click** → Open preview, Reveal in Explorer, To
  plot, To sketch, To slideshow. The last three insert the matching
  slash into Chat and store results as files (figures / sketches /
  `slideshows/`). No Plot tab.
- Wiki preview renders tables, PNG figures, `[[wikilinks]]`, and source
  filenames you can right-click to reveal in Explorer / OS / open.
- `/thrusters` arms Mars Hopper in a webview.

## How to run the spike

Open this repo (or a CE workspace folder) in VS Code, then **Run →
Start Debugging** on the `Switch Bay` launch config in
`extensions/switchbay/.vscode/launch.json` (F5). A second Extension
Development Host window opens. There is no daemon to start. Confirm
nothing is listening on `:8765`.

Compile:

```
pnpm --dir extensions/switchbay install
pnpm --dir extensions/switchbay run compile
```

MCP worker (spawned by the extension, not by you):

```
CSWY_PROFILE=vscode CSWY_WORKSPACE=/path/to/vault \
  PYTHONPATH=src .venv/bin/python -m switchbay.mcp_server
```

## Verdict

Accept if a CE folder in VS Code can: browse the wiki tree, show Atlas,
click through to markdown, preview wikilinks/figures, run `/curate`
from Chat, watch a DAG — with `:8765` empty and Copilot as the only
sign-in.

Kill or fall back to a sidecar **worker** (still not an HTTP daemon) if
`vscode.lm` cannot drive a multi-minute DAG, or if too many tools are
secretly HTTP UI puppets.

## Out of scope

Marketplace publish, deleting PWA tabs, enterprise installer, porting
Univer/DuckDB/the rail/`llmgateway`, the HTML-slideshow migration on
`main`.
