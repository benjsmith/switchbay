# Switch Bay VS

In-tree VS Code extension (alternative install of Switch Bay). No daemon.
Open a curiosity-engine folder (`wiki/` + `vault/`) and F5 from this checkout.

See [`docs/vscode-plugin.md`](../../docs/vscode-plugin.md) for the keep/drop
list and verdict. Graph/Atlas is built from `frontend/` (`pnpm --dir frontend
run build:webview`) so PWA and the webview share one widget.

## Debug

1. Branch `exp/vscode-plugin`. File → Open Workspace from File →
   `switchbay.code-workspace`.
2. Run and Debug → **Switch Bay VS**.
3. In the Extension Development Host, open a CE folder.

```
make vscode-compile
```

Chat: `@switchbay` — `/thrusters` `/curate` `/plot` `/deck` `/sketch`.

**Switch Bay VS: Local models…** probes Ollama, llama.cpp, and MLX and
publishes them to Chat / Agents.

Custom agents: Auto, Curator, Reviewer. Investigator is subagent-only.
