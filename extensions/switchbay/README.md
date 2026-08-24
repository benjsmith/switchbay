# Switch Bay (VS Code experiment)

No daemon. Open a curiosity-engine folder (`wiki/` + `vault/`) and F5 this
extension from the Switch Bay checkout.

See [`docs/vscode-plugin.md`](../../docs/vscode-plugin.md) for the
hypothesis, keep/drop list, and verdict criteria.

## Debug

From the Switch Bay repo root in VS Code:

1. `pnpm --dir extensions/switchbay install`
2. F5 (launch config **Switch Bay**)
3. In the Extension Development Host, open a CE workspace if this repo is not one
4. Confirm `lsof -i :8765` is empty

Chat: `@switchbay` — slashes `/thrusters`, `/curate`, `/plot`, `/deck`, `/sketch`.

`/curate` opens the **VS Code Agents window** on the bundled **Auto**
custom agent (Local harness + Switch Bay MCP) and writes a DAG snapshot
the Agent Dashboard watches. Also: **Switch Bay: Curate** in the palette.

Custom agents in the Agents dropdown: Auto, Curator, Reviewer.
Investigator is subagent-only.
