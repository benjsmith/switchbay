import * as vscode from "vscode";

export async function pickModel(): Promise<vscode.LanguageModelChat | undefined> {
  const models = await vscode.lm.selectChatModels({ vendor: "copilot" });
  if (models.length) return models[0];
  const any = await vscode.lm.selectChatModels();
  return any[0];
}
