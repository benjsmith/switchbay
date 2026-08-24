# Switch Bay (VS Code experiment)

No daemon. Open a curiosity-engine folder (`wiki/` + `vault/`) and F5 this
extension from the Switch Bay checkout.

See [`docs/vscode-plugin.md`](../../docs/vscode-plugin.md) for the
hypothesis, keep/drop list, and verdict criteria.

## Debug

**F5 only works in the Switch Bay checkout**, on branch `exp/vscode-plugin`,
with launch config **Switch Bay**. If you get a “Select debugger” list
(Chrome / Node / Edge), you are in the wrong window or the wrong branch.

1. In a **normal** VS Code window (title is `switchbay`, **not**
   `[Extension Development Host]`), `git checkout exp/vscode-plugin`.
2. File → Open Workspace from File → `switchbay.code-workspace`
   (or open the repo folder so `.vscode/launch.json` loads).
3. Run and Debug (`⇧⌘D`) → dropdown **Switch Bay** → green play.
   Do not press F5 on the Welcome tab inside the Extension Development Host.
4. A second window titled `[Extension Development Host]` opens. **There**,
   File → Open Folder on your CE workspace (`curiosity-test`). Then click
   the Switch Bay activity-bar icon.

Compile uses `extensions/switchbay/node_modules/.bin/tsc` via a login
shell (not `npm`), so Dock-launched VS Code should not exit 127.

If Wiki is still empty after that, Output → **Switch Bay**, then the
refresh control on the Wiki view.

Chat: `@switchbay` — slashes `/thrusters`, `/curate`, `/plot`, `/deck`, `/sketch`.

`/curate` opens the **VS Code Agents window** on the bundled **Auto**
custom agent (Local harness + Switch Bay MCP) and writes a DAG snapshot
the Agent Dashboard watches. Also: **Switch Bay: Curate** in the palette.

Custom agents in the Agents dropdown: Auto, Curator, Reviewer.
Investigator is subagent-only.
