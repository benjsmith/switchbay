import * as vscode from "vscode";

/**
 * Run-scoped Auto orchestration. The spike does not start a daemon.
 * A later step ports orchestration.py's investigate/verify/synthesize
 * DAG onto vscode.lm + MCP tools, writing snapshots under the existing
 * on-disk run folders so the Agent Dashboard can file-watch them.
 */
export async function startCurate(prompt: string): Promise<string> {
  const trimmed = prompt.trim() || "curate the wiki";
  await vscode.commands.executeCommand("switchbay.openAgents");
  return (
    `Would start a run-scoped Auto DAG for: ${trimmed}\n\n`
    + `Not wired yet on this spike — the chat participant still has wiki/CE `
    + `MCP tools, so you can ask it to \`ce_lint\` / \`ce_sweep\` / `
    + `\`propose_wiki_page\` directly. Nothing is listening on :8765.`
  );
}
