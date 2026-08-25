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
  Agents window: Auto / Curator / Reviewer custom agents (Local harness)
  vscode.lm  (Copilot models)
       │ stdio MCP (also registered for Local Agents)
       ▼
  python -m switchbay.mcp_server    curiosity-engine scripts
  CSWY_PROFILE=vscode

`/curate` does two things, on purpose:

1. **VS Code-native** — open the Agents window and start a Local session
   on the **Auto** custom agent (Investigator/Reviewer subagents + MCP).
2. **Switch Bay-native** — write a DAG snapshot under the machine-local
   runs dir and prime it with read-only MCP (`ce_epoch_summary`,
   `ce_lint`). The Agent Dashboard file-watches that. Writing still
   happens in the Agents session via `propose_wiki_page`.
```

Hard rules:

- Plugin path never imports `aiohttp`.
- Webviews never `fetch("http://127.0.0.1:8765/...")`.
- Tools that still call `_daemon_json` / `/api/*` are out of the plugin
  allowlist (`switchbay.plugin_tools`).

## Interaction

- Graph is the **classic** SVG force graph. Edges come from CE's
  `.curator/graph.kuzu` (`WikiLink` + `Depicts`). If that file is
  **missing**, Open Graph runs `graph.py rebuild` then reads kuzu —
  it never paints markdown-harvested edges. The **view:** control
  switches to Knowledge Atlas.
- Graph node **click** → open the `.md` in a normal VS Code tab.
- Wiki tree / graph clicks reuse editor groups from the current split
  (MD-only, preview-only, or paired MD+preview, cycling when several
  groups are open). VS Code's own reuse is `workbench.editor.enablePreview`
  in the *active* group; `ViewColumn.Beside` always splits.
- Graph node **right-click** → Open preview, Reveal in Explorer, To
  plot, To sketch, To slideshow. The last three insert the matching
  slash into Chat and store results as files (figures / sketches /
  `slideshows/`). No Plot tab.
- Wiki preview renders tables, PNG figures, `[[wikilinks]]`, and source
  filenames you can right-click to reveal in Explorer / OS / open.
- `/thrusters` arms Mars Hopper in a webview.
- `/curate` (and **Switch Bay: Curate**) opens a VS Code Agents session
  on Auto and a Switch Bay DAG on disk. Opt-in:
  `extensions.supportAgentsWindow["switchbay.switchbay"] = true`.
- Agent Dashboard restores the PWA's extra panels (Agent Space DAG,
  running/finished, tools, rules, palettes, Copilot models, skills)
  from disk + MCP + `vscode.lm`. No `:8765`.

## How to run the spike

Open **this** checkout on `exp/vscode-plugin` (File → Open Workspace
from File → `switchbay.code-workspace`), then Run and Debug → **Switch
Bay**. Do not F5 inside the `[Extension Development Host]` window — that
folder has no launch config, so VS Code shows the Chrome/Node picker.

A second Extension Development Host window opens. Open your CE folder
there. Nothing listens on `:8765`.

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
