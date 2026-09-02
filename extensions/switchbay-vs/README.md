# Switch Bay VS

Knowledge-graph workbench over a curiosity-engine folder. **No always-on
Python HTTP server.** VS Code owns the chrome; Switch Bay owns the wiki,
graph, MCP tools, and Agents session.

Install and update walkthrough: [docs/vscode.md](https://github.com/benjsmith/switchbay/blob/main/docs/vscode.md)
in the Switch Bay repo.

![Switch Bay VS icon](media/icon.png)

## What you get

- **Wiki**, **Files**, and **Projects** in the activity bar (Wiki is the same WikiPage set as Graph, from `.curator/graph.kuzu`; Files is the wiki folder on disk; both show the wiki name at the top. Refresh rebuilds the graph)
- **Graph / Atlas** webview (edges from `.curator/graph.kuzu`)
- Wiki markdown preview with `[[wikilinks]]`, `![[figures/_assets/…]]`, and clickable sources
- **Ingest file / folder** from the Wiki view and Explorer (CE `local_ingest.py`)
- **Stop** on the Agent Dashboard (retires the DAG; tries to cancel Chat)
- Chat participant `@switchbay` (`/curate`, `/thrusters`, …)
- MCP stdio worker: `python -m switchbay.mcp_server` (`CSWY_PROFILE=vscode`)
- Agent Dashboard (DAG snapshot on disk, not a live daemon)
- **Orchestration effort** slider (Economy → Maximum) for Auto
- **Schedules** for named agents (Auto, Curator, Draw, …) while VS Code is open
- Local models helper for Ollama, llama.cpp, and MLX
- **Operating modes:** wiki-native, code-repo (`.curiosity/config.toml` / `switchbay.wikiRoot`), dual cockpit (PWA or VS Code for the Web hosts overnight desks; this window codes)

## Operating modes

| Mode | What you open | What Switch Bay attaches to |
| --- | --- | --- |
| Wiki-native | The CE folder (`wiki/` + `vault/`) | That folder |
| Code-repo | A git project with `.curiosity/config.toml` | The wiki named in the pointer (`switchbay.wikiRoot` overrides) |
| Dual cockpit | Same wiki, two hosts | Desktop VS Code for coding; PWA or VS Code for the Web for 24/7 desks. One writer at a time. |

**Register this folder with a wiki…** (Wiki view title, welcome view, Dashboard) writes the pointer and registers the project-dir. From a wiki window it asks which folders to link. The **SBH** pill in the status bar turns the knowledge harness on or off in *this* window (`@switchbay /sbh on|off`). Leave SBH off in coding windows; on in the wiki window.

## Requirements

This VSIX is the VS Code UI. The Python workbench still lives in a
[Switch Bay](https://github.com/benjsmith/switchbay) git checkout.
Requires **VS Code 1.134+**.

1. Clone Switch Bay and run `make install`.
2. Open a curiosity-engine folder (`wiki/` + `vault/`).
3. Command Palette → **Switch Bay VS: Configure Python…** and pick that
   checkout (the folder with `src/switchbay` and `.venv`).

First-run prompts if `import switchbay` fails. You can re-run the command
any time. Settings written: `switchbay.repoRoot` and `switchbay.pythonPath`
(user settings).

Optional: GitHub Copilot for Chat / Agents models, **or** local Ollama
(`:11434`), llama.cpp (`:8080`), or MLX (`:8888`) via **Switch Bay VS:
Local models…**.

## Commands

| Command | What it does |
| --- | --- |
| Open Graph | Classic force graph; **view:** switches to Atlas |
| Open Wiki Preview | Rendered wiki page with sources |
| Open Agent Dashboard | DAG / tools / rules / models |
| Curate (Agents session) | Opens a VS Code Agents session on Auto |
| Set orchestration effort… | Economy / Balanced / Maximum (also a slider on the Dashboard) |
| Schedule a named agent… | Recurring prompt on Auto, Curator, Draw, … |
| Run named agent… | Open a Local session on a shipped or workspace agent |
| Update extension… | Sideload a newer VSIX from this checkout |
| Fire Thrusters | Mars Hopper webview |
| Rebuild Wiki Viewer | CE `wiki_render.py` |
| Refresh Wiki & Projects | Re-scan `wiki/**/*.md` on disk |
| Ingest file… / folder… | CE `local_ingest.py` into the resolved vault |
| Register this folder with a wiki… | One-click Mode B pointer + project-dir registry |
| Set wiki folder… | Point at a wiki without rewriting the pointer |
| Knowledge harness (SBH)… | On/off for this window (status bar pill) |
| Configure Python… | Point at a Switch Bay checkout |
| Local models… | Discover Ollama / llama.cpp / MLX |

Chat: `@switchbay` with `/thrusters` `/curate` `/plot` `/deck` `/sketch`.

Custom agents: Auto, Curator, Reviewer. Investigator is subagent-only.

## Sideload from this repo

```
make vsix
code --install-extension dist/switchbay-vs-0.3.17.vsix
```

That same command **updates** an older sideload (same `publisher` + `name`). Then **Developer: Reload Window**. Command Palette → **Switch Bay VS: Update extension…** walks the same path if `dist/*.vsix` is already built.

Sideload testers: after `make vsix`, install the VSIX again and
**Developer: Reload Window**. Schedules fire only while VS Code is open.

## License

[FSL-1.1-ALv2](https://github.com/benjsmith/switchbay/blob/main/LICENSE)
(Functional Source License, Apache 2.0 after two years).
