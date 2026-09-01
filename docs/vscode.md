# Switch Bay VS

Switch Bay inside VS Code: the same curiosity-engine wiki, Graph/Atlas,
MCP tools, and Auto agents — **no always-on daemon**. VS Code owns
windows, Chat, and Copilot sign-in. Closing VS Code stops scheduled
runs.

Requires **VS Code 1.134+**. Not on the Marketplace yet; sideload a VSIX
from this repo. The browser PWA (always-on local daemon) is a separate
product — see the root README.

## Install

1. Clone Switch Bay and install Python deps (once per machine):

   ```sh
   git clone https://github.com/benjsmith/switchbay.git
   cd switchbay
   make install
   ```

2. Package and sideload:

   ```sh
   make vsix
   code --install-extension dist/switchbay-vs-0.3.16.vsix
   ```

3. Open a curiosity-engine folder (`wiki/` + `vault/`).
4. Command Palette → **Switch Bay VS: Configure Python…** and pick the
   Switch Bay checkout (the folder with `src/switchbay` and `.venv`).

First-run also prompts if `import switchbay` fails. Settings written:
`switchbay.repoRoot`, `switchbay.pythonPath`.

## Update

Sideload installs do **not** auto-update. Same id
(`switchbay.switchbay-vs`) is replaced by installing a newer VSIX:

```sh
make vsix
code --install-extension dist/switchbay-vs-0.3.15.vsix
```

Then **Developer: Reload Window**. Or Command Palette → **Switch Bay VS:
Update extension…** if `dist/*.vsix` is already built.

## Operating modes

| Mode | Open in VS Code | Wiki Switch Bay uses |
| --- | --- | --- |
| **Wiki-native** | The curiosity-engine folder (`wiki/` + `vault/`) | That folder |
| **Code-repo** | A code or documents project | `.curiosity/config.toml` `workspace = …`, or setting `switchbay.wikiRoot` |
| **Dual cockpit** | Coding window on a code-repo (or wiki) | Same wiki on disk as the PWA / a VS Code for the Web tab that **Keep running 24/7**. Neither host starts the other. One curator writing at a time. |

**One-click register:** in a code or docs window, Wiki view **Register this folder with a wiki…** (or the welcome button). Pick the shared wiki and a project tag. That writes `.curiosity/config.toml` and adds the folder to the wiki’s `.curator/project-dirs.json`. From a wiki window the same command links *other* folders into this wiki.

**SBH** (status bar, left): knowledge harness for *this window*. Click → On / Off. `@switchbay /sbh`, `/sbh on`, `/sbh off`. Off = coding Chat only. On = `@switchbay` / Curator / wiki MCP.

PWA **+ Add workspace** adds a *wiki* to the PWA switcher. It does not write a code-repo pointer. Register repos from VS Code as above (or CE `setup.sh --register-code-repo`).

Explorer context **Ingest into wiki vault** runs CE `local_ingest.py` (cheap pypdf/text extract + `vault.db` index). Vision is **not** used here — CE flags `multimodal_recommended` when figures/tables need a later CURATE wave. Files outside the wiki use `--source-path-only` (originals stay put).

## What to open

| Surface | How |
| --- | --- |
| Wiki / Projects | Activity bar (Switch Bay icon). Same WikiPage nodes as Graph (`graph.kuzu`). **Refresh** runs `graph.py rebuild`. |
| Graph / Atlas | Wiki view title **Open Graph**; **view:** switches Atlas. Center-top search highlights nodes and Wiki-tree files; **×** clears. |
| Wiki preview | Editor title on a `wiki/**/*.md` tab |
| Agent Dashboard | Wiki view title, or **Open Agent Dashboard** |
| Chat | `@switchbay` (`/curate`, `/thrusters`, `/plot`, `/deck`, `/sketch`) |
| Custom agents | Agents dropdown (Auto, Curator, Reviewer) plus workspace `.github/agents/*.agent.md` |

## Agent Dashboard

- **Agent Space** — one live DAG. `/curate` shows CE Phase 1
  (`ce_wave_prime`) then the Curator wave, not Investigate → Synthesize.
  Auto research desks still use investigators. Copilot Chat does not
  stream tool calls into this panel, so wiki page writes are the
  heartbeat. Curator calls `orchestration_report` when a wave is done
  (Chat staying open with Keep curating is not “still running”). Quiet
  wiki writes also retire the DAG. **Mark finished** if you want to
  force it. **Stop** tries to cancel the Chat request and always retires
  the card.
- **Orchestrator** — Economy → Maximum. Agent count is an outcome of this
  slider, not a second control. Workspace setting
  `switchbay.orchestrationPreference`. Economy is CE’s single-session
  fallback on a **local** model (the Curator *is* the worker). On a
  provider, Balanced/Maximum dispatch CE workers (NumericReviewer,
  TableExtractor, page workers, then BatchReviewer) as the skill’s
  planner → workers → reviewer wave. Auto desks still use Investigators.
- **Custom agents** — Chat personas (`.agent.md`). `/create-agent` writes
  `.github/agents/`. Not the same as Skills.
- **Skills** — `SKILL.md` toolkits (`curiosity-engine`, …).
- **Schedules** — recurring prompt on a named agent, with an optional
  duration. Stored in `.workbench/state/schedules.json`. Ticks only
  while this VS Code window is open.
- **Agent desks** — **Set up** writes `.workbench/state/desks.json`
  (edit the prompt there). `duration` accepts `15 min`, `15 mins`,
  `0.25` (hours), or `2h`. **Activate** / **Deactivate** turn the
  desk on or off without firing immediately. **Add desk** or
  `@switchbay /desk` appends a stub. Research only; never trades.
  **Keep running 24/7** opens VS Code for the Web or a Remote Tunnel
  so a browser tab can be the host.
- **Models** — `vscode.lm` (Copilot Language Model API) plus any local
  backends you add. This is **not** the Chat model picker (Auto routing,
  Copilot CLI, subscriber SKUs).

## Models other than GitHub Copilot

Command Palette → **Switch Bay VS: Local models…** (also **Add Ollama /
MLX / llama.cpp…** on the Dashboard). It probes Ollama `:11434`,
llama.cpp `:8080` (plus GGUFs on disk), and MLX (`mlx-serve list` /
`:11234` / `:8888`). If `mlx-serve` is installed it is started so the
picker can see pulled models. Pull actions: Ollama tag, llama.cpp GGUF
(Hugging Face repo), MLX tag (`mlx-serve pull`). Added models register
as vendor **Switch Bay VS Local**. Copilot subscriber models stay in
Copilot Chat’s own picker.

## Develop (F5)

Open `switchbay.code-workspace` → Run and Debug →
**Switch Bay VS**. Do not F5 inside the Extension Development Host
window. After code changes, reload that host window. Sideload testers
should use `make vsix` instead (above).

## `/curate` and Copilot MCP

`/curate` starts the **Curator** custom agent in **editor Chat** (a new
session). Curator is the curiosity-engine orchestrator (`ce_wave_prime`
→ pick-mode → Phase 2). It does not send the prompt into the dedicated
Agents window — that window does not inherit the query, so it used to
open empty.

Wiki tools come from MCP server **switchbay** (workspace
`.vscode/mcp.json`, Python from **Configure Python…**). Copilot validates
every tool schema before a turn; one bad array schema (`create_slideshow`
historically) drops the whole Switch Bay toolset and the chat sits idle.

If Chat shows `Failed to validate tool mcp_switchbay_create_slideshow`
or “MCP tools unavailable”:

1. Command Palette → **Developer: Reload Window** (after sideloading a
   new VSIX).
2. **MCP: List Servers** → restart **switchbay**.
3. Start a **new** Copilot chat, then `/curate` again. An existing thread
   keeps the poisoned tool list even after the schema is fixed.

## Copilot approvals vs the tool allowlist

The Auto/Curator `tools:` frontmatter (`switchbay/*`) **enables** Switch
Bay MCP tools. It does not skip Copilot’s confirmation. MCP tools always
prompt until you trust them or the server is sandboxed.

The extension writes `.vscode/mcp.json` with the sandbox **off**.
Copilot’s sandbox wrapper needs `rg` on the GUI app PATH (not Homebrew)
and otherwise exits 1 before Python starts — Chat then has no wiki
tools. Approve **switchbay** once via **Chat: Manage Tool Approval**.
Reload the window and restart MCP **switchbay** after a VSIX update.

On **Windows** (no MCP sandbox), or if you still see **Allow in this
Session**:

1. Approve once with **Allow in this Session**, or
2. Command Palette → **Chat: Manage Tool Approval** → trust the
   **switchbay** MCP server (top-level checkbox).

Do not turn on `chat.tools.global.autoApprove` / `/yolo` just for
Switch Bay — that bypasses every tool in every workspace.
