# Switch Bay VS

Switch Bay inside VS Code: the same curiosity-engine wiki, Graph/Atlas,
MCP tools, and Auto agents — **no daemon**, nothing on `:8765`. VS Code
owns windows, Chat, and Copilot sign-in. Closing VS Code stops scheduled
runs.

Requires **VS Code 1.134+**. Not on the Marketplace yet; sideload a VSIX
from this repo. The PWA at `http://127.0.0.1:8765` is a separate product
(see the root README).

## Install

1. Clone Switch Bay and install Python deps (once per machine):

   ```sh
   git clone https://github.com/benjsmith/switchbay.git
   cd switchbay
   git checkout exp/vscode-plugin   # until this lands on main
   make install
   ```

2. Package and sideload:

   ```sh
   make vsix
   code --install-extension dist/switchbay-vs-0.2.0.vsix
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
code --install-extension dist/switchbay-vs-0.2.0.vsix
```

Then **Developer: Reload Window**. Or Command Palette → **Switch Bay VS:
Update extension…** if `dist/*.vsix` is already built.

## What to open

| Surface | How |
| --- | --- |
| Wiki / Projects | Activity bar (Switch Bay icon) |
| Graph / Atlas | Wiki view title **Open Graph**; **view:** switches Atlas |
| Wiki preview | Editor title on a `wiki/**/*.md` tab |
| Agent Dashboard | Wiki view title, or **Open Agent Dashboard** |
| Chat | `@switchbay` (`/curate`, `/thrusters`, `/plot`, `/deck`, `/sketch`) |
| Custom agents | Agents dropdown (Auto, Curator, Reviewer) plus workspace `.github/agents/*.agent.md` |

## Agent Dashboard

- **Orchestrator** — Economy → Maximum. Agent count is an outcome of this
  slider, not a second control. Workspace setting
  `switchbay.orchestrationPreference`.
- **Custom agents** — Chat personas (`.agent.md`). `/create-agent` writes
  `.github/agents/`. Not the same as Skills.
- **Skills** — `SKILL.md` toolkits (`curiosity-engine`, …).
- **Schedules** — recurring prompt on a named agent. Stored in
  `.workbench/state/schedules.json`. Ticks only while VS Code is open.
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

Open `switchbay.code-workspace` on this branch → Run and Debug →
**Switch Bay VS**. Do not F5 inside the Extension Development Host
window. After code changes, reload that host window. Sideload testers
should use `make vsix` instead (above).
