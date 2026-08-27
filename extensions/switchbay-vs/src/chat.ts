import * as vscode from "vscode";
import { getMcp } from "./mcp";
import { pickModel } from "./lm";
import { addBlankDesk } from "./desks";
import { ensureLiveRun, startCurate } from "./orch";
import { workspaceFsPath } from "./paths";

const SYSTEM = `You are Switch Bay inside VS Code. The open folder is the workspace.
QUERY: ce_graph_retrieve first (entity gate), then read pages. search_wiki is catalog only.
Cite [[wikilinks]] and (vault:...). One probing follow-up. Do not invent sources.
Wiki writes (analyses): ce_score_diff then ce_wiki_commit. /curate is the Curator agent.
Plots: save_plot. Slideshows: create_slideshow. Sketches: author_sketch.
There is no Sheet, Table, Plot tab, or daemon.`;

const SLASH_HINTS: Record<string, string> = {
  plot: "Author 2–4 Vega-Lite plots from the given wiki page or data, call save_plot, and describe the figure paths under wiki/figures/.",
  deck: "Author an HTML slideshow with create_slideshow about the given topic. Link it from the wiki with [[slideshow:slug]].",
  sketch: "Author a sketch with author_sketch. Files go in .workbench/sketches/. Tell the user to install the Switch Bay Sketch companion to edit them visually.",
};

export function registerChat(context: vscode.ExtensionContext): vscode.ChatParticipant {
  const participant = vscode.chat.createChatParticipant(
    "switchbay.participant",
    async (request, _ctx, stream, token) => {
      const cmd = request.command || "";
      if (cmd === "thrusters") {
        await vscode.commands.executeCommand("switchbay.fireThrusters");
        stream.markdown("Thrusters armed. Hopper is in a tab.");
        return;
      }
      if (cmd === "curate") {
        const { text } = await startCurate(context, request.prompt);
        stream.markdown(text);
        return;
      }
      if (cmd === "desk") {
        const ws = workspaceFsPath();
        if (!ws) {
          stream.markdown("Open a curiosity-engine folder first.");
          return;
        }
        const result = addBlankDesk(ws);
        await vscode.window.showTextDocument(vscode.Uri.file(result.path), { preview: false });
        stream.markdown(
          "Added a desk stub in `.workbench/state/desks.json`. Edit the prompt and duration, "
          + "then **Activate** on the Agent Dashboard. **Deactivate all** turns overnight desks off.",
        );
        return;
      }
      const hint = SLASH_HINTS[cmd];
      const user = hint
        ? `${hint}\n\nUser: ${request.prompt}`
        : request.prompt;
      const ws = workspaceFsPath();
      if (ws) ensureLiveRun(ws, request.prompt || cmd || "Chat", { via: "chat", agent: "Auto", kind: "chat" });
      return runTurn(context, user, stream, token);
    },
  );
  participant.iconPath = vscode.Uri.joinPath(context.extensionUri, "media", "icon.svg");
  context.subscriptions.push(participant);
  return participant;
}

async function runTurn(
  context: vscode.ExtensionContext,
  prompt: string,
  stream: vscode.ChatResponseStream,
  token: vscode.CancellationToken,
): Promise<void> {
  const model = await pickModel();
  if (!model) {
    stream.markdown("Sign in to GitHub Copilot (or another `vscode.lm` vendor) — Switch Bay does not keep API keys.");
    return;
  }
  let tools: vscode.LanguageModelChatTool[] = [];
  try {
    const mcp = await getMcp(context);
    const listed = await mcp.listTools();
    tools = listed.map((t) => ({
      name: t.name,
      description: t.description || t.name,
      inputSchema: t.inputSchema,
    }));
  } catch (err) {
    stream.markdown(`MCP worker did not start (${(err as Error).message}). Chat will answer without wiki tools.\n\n`);
  }

  const messages: vscode.LanguageModelChatMessage[] = [
    vscode.LanguageModelChatMessage.User(SYSTEM + "\n\n" + prompt),
  ];

  for (let round = 0; round < 8; round++) {
    if (token.isCancellationRequested) return;
    const response = await model.sendRequest(messages, tools.length ? { tools } : {}, token);
    const toolCalls: vscode.LanguageModelToolCallPart[] = [];
    let assistant = "";
    for await (const part of response.stream) {
      if (part instanceof vscode.LanguageModelTextPart) {
        assistant += part.value;
        stream.markdown(part.value);
      } else if (part instanceof vscode.LanguageModelToolCallPart) {
        toolCalls.push(part);
      }
    }
    if (!toolCalls.length) return;

    const resultParts: vscode.LanguageModelToolResultPart[] = [];
    try {
      const mcp = await getMcp(context);
      for (const call of toolCalls) {
        stream.markdown(`\n\n*${call.name}*\n`);
        const args = (call.input ?? {}) as Record<string, unknown>;
        const out = await mcp.callTool(call.name, args);
        stream.markdown("```\n" + out.text.slice(0, 2000) + "\n```\n");
        resultParts.push(new vscode.LanguageModelToolResultPart(call.callId, [
          new vscode.LanguageModelTextPart(out.text.slice(0, 8000)),
        ]));
      }
    } catch (err) {
      stream.markdown(`Tool call failed: ${(err as Error).message}`);
      return;
    }
    messages.push(vscode.LanguageModelChatMessage.Assistant([
      ...(assistant ? [new vscode.LanguageModelTextPart(assistant)] : []),
      ...toolCalls,
    ]));
    messages.push(vscode.LanguageModelChatMessage.User(resultParts));
  }
}
