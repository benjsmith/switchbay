/**
 * Settings-like helper: discover / install local MLX, llama.cpp, and
 * Ollama backends, persist them in VS Code config, and publish them
 * as chat models (LanguageModelChatProvider) so Agents/Chat can use
 * them without the Switch Bay daemon.
 */
import * as os from "os";
import * as vscode from "vscode";

export type LocalBackend = "ollama" | "llamacpp" | "mlx";

export type LocalModel = {
  backend: LocalBackend;
  name: string;
  model: string;
  baseUrl: string;
};

const CONFIG_KEY = "switchbay.localModels";
const VENDOR = "switchbay-local";

const DEFAULTS: Record<LocalBackend, { label: string; port: number; tags: string }> = {
  ollama: { label: "Ollama", port: 11434, tags: "http://127.0.0.1:11434/api/tags" },
  llamacpp: { label: "llama.cpp", port: 8080, tags: "http://127.0.0.1:8080/v1/models" },
  mlx: { label: "MLX", port: 8888, tags: "http://127.0.0.1:8888/v1/models" },
};

function configured(): LocalModel[] {
  const raw = vscode.workspace.getConfiguration("switchbay").get<LocalModel[]>(CONFIG_KEY.slice("switchbay.".length));
  return Array.isArray(raw) ? raw.filter((m) => m && m.model && m.baseUrl) : [];
}

async function fetchJson(url: string, timeoutMs = 2500): Promise<unknown | null> {
  const ac = new AbortController();
  const t = setTimeout(() => ac.abort(), timeoutMs);
  try {
    const res = await fetch(url, { signal: ac.signal });
    if (!res.ok) return null;
    return await res.json();
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}

type Probe = { backend: LocalBackend; ok: boolean; models: string[]; hint: string };

async function probe(): Promise<Probe[]> {
  const ollama = await fetchJson("http://127.0.0.1:11434/api/tags");
  const ollamaModels = Array.isArray((ollama as { models?: { name?: string }[] } | null)?.models)
    ? (ollama as { models: { name?: string }[] }).models.map((m) => m.name || "").filter(Boolean)
    : [];

  const llama = await fetchJson("http://127.0.0.1:8080/v1/models");
  const llamaModels = Array.isArray((llama as { data?: { id?: string }[] } | null)?.data)
    ? (llama as { data: { id?: string }[] }).data.map((m) => m.id || "").filter(Boolean)
    : [];

  const mlxModels: string[] = [];
  let mlxOk = false;
  if (process.platform === "darwin" && os.arch() === "arm64") {
    for (let port = 8888; port <= 8892; port++) {
      const mlx = await fetchJson(`http://127.0.0.1:${port}/v1/models`);
      const ids = Array.isArray((mlx as { data?: { id?: string }[] } | null)?.data)
        ? (mlx as { data: { id?: string }[] }).data.map((m) => m.id || "").filter(Boolean)
        : [];
      if (ids.length || mlx) {
        mlxOk = true;
        mlxModels.push(...ids.map((id) => (ids.length ? `${id} (:${port})` : `:${port}`)));
        break;
      }
    }
  }

  return [
    {
      backend: "ollama",
      ok: ollamaModels.length > 0 || ollama != null,
      models: ollamaModels,
      hint: ollamaModels.length
        ? `${ollamaModels.length} model(s) on :11434`
        : "Not running. Install from ollama.com or `brew install ollama`, then `ollama serve`.",
    },
    {
      backend: "llamacpp",
      ok: llama != null,
      models: llamaModels,
      hint: llama
        ? (llamaModels.length ? llamaModels.join(", ") : "server on :8080")
        : "Not running. `brew install llama.cpp` then `llama-server -m <model.gguf> --port 8080`.",
    },
    {
      backend: "mlx",
      ok: mlxOk,
      models: mlxModels,
      hint: process.platform === "darwin" && os.arch() === "arm64"
        ? (mlxOk ? (mlxModels.join(", ") || "mlx_lm.server on :8888")
          : "Not running. `uv tool install mlx-lm` then `mlx_lm.server --port 8888`.")
        : "MLX is Apple silicon only.",
    },
  ];
}

async function persist(models: LocalModel[]): Promise<void> {
  await vscode.workspace.getConfiguration("switchbay").update(
    "localModels",
    models,
    vscode.ConfigurationTarget.Global,
  );
}

function baseUrlFor(backend: LocalBackend, extraPort?: string): string {
  if (backend === "ollama") return "http://127.0.0.1:11434/v1";
  if (backend === "mlx") {
    const p = extraPort?.match(/:(\d+)/)?.[1] || "8888";
    return `http://127.0.0.1:${p}/v1`;
  }
  return "http://127.0.0.1:8080/v1";
}

export async function configureLocalModels(): Promise<void> {
  const scanning = vscode.window.setStatusBarMessage("$(sync~spin) Scanning local models…");
  let probes: Probe[];
  try {
    probes = await probe();
  } finally {
    scanning.dispose();
  }

  const picks: vscode.QuickPickItem[] = [];
  for (const p of probes) {
    picks.push({
      label: `${p.ok ? "$(check)" : "$(circle-slash)"} ${DEFAULTS[p.backend].label}`,
      description: p.ok ? "running" : "not found",
      detail: p.hint,
      kind: vscode.QuickPickItemKind.Default,
    });
    for (const name of p.models) {
      picks.push({
        label: `    $(add) ${name}`,
        description: `Add ${DEFAULTS[p.backend].label} model to VS Code`,
        detail: p.backend,
      });
    }
  }
  picks.push({ label: "", kind: vscode.QuickPickItemKind.Separator });
  picks.push({ label: "$(cloud-download) Pull an Ollama tag…", description: "ollama pull <tag>" });
  picks.push({ label: "$(link-external) Install Ollama…", description: "Open ollama.com/download" });
  if (process.platform === "darwin" && os.arch() === "arm64") {
    picks.push({ label: "$(link-external) MLX install hint", description: "uv tool install mlx-lm" });
  }
  picks.push({ label: "$(server) llama.cpp install hint", description: "brew install llama.cpp" });
  const saved = configured();
  if (saved.length) {
    picks.push({ label: "", kind: vscode.QuickPickItemKind.Separator });
    picks.push({
      label: `$(clear-all) Clear ${saved.length} saved local model(s) from settings`,
    });
  }

  const choice = await vscode.window.showQuickPick(picks, {
    title: "Switch Bay VS · Local models",
    placeHolder: "Add a running Ollama / llama.cpp / MLX model to VS Code Chat & Agents",
    ignoreFocusOut: true,
  });
  if (!choice || choice.kind === vscode.QuickPickItemKind.Separator) return;

  if (choice.label.includes("Pull an Ollama")) {
    const tag = await vscode.window.showInputBox({
      title: "ollama pull",
      placeHolder: "qwen2.5-coder:7b",
      prompt: "Tag to pull. Requires `ollama` on PATH and the daemon running.",
    });
    if (!tag) return;
    const term = vscode.window.createTerminal({ name: "ollama pull" });
    term.show();
    term.sendText(`ollama pull ${tag}`);
    return;
  }
  if (choice.label.includes("Install Ollama")) {
    await vscode.env.openExternal(vscode.Uri.parse("https://ollama.com/download"));
    return;
  }
  if (choice.label.includes("MLX install")) {
    const term = vscode.window.createTerminal({ name: "mlx-lm" });
    term.show();
    term.sendText("uv tool install mlx-lm || pip install mlx-lm");
    return;
  }
  if (choice.label.includes("llama.cpp install")) {
    const term = vscode.window.createTerminal({ name: "llama.cpp" });
    term.show();
    term.sendText("brew install llama.cpp || echo 'See https://github.com/ggml-org/llama.cpp'");
    return;
  }
  if (choice.label.includes("Clear")) {
    await persist([]);
    void vscode.window.showInformationMessage("Cleared Switch Bay VS local models from user settings.");
    return;
  }

  const backend = (choice.detail || "") as LocalBackend;
  if (!backend || !(backend in DEFAULTS)) return;
  const rawName = choice.label.replace(/^\s*\$\([^)]+\)\s*/, "").trim();
  const model = rawName.replace(/\s*\(:\d+\)\s*$/, "");
  const next: LocalModel = {
    backend,
    name: `${DEFAULTS[backend].label} · ${model}`,
    model,
    baseUrl: baseUrlFor(backend, rawName),
  };
  const models = configured().filter((m) => !(m.backend === next.backend && m.model === next.model));
  models.push(next);
  await persist(models);
  void vscode.window.showInformationMessage(
    `Added ${next.name}. It appears under Chat / Agents as vendor “Switch Bay VS Local”.`,
  );
}

function roleOf(role: vscode.LanguageModelChatMessageRole): "user" | "assistant" | "system" {
  return role === vscode.LanguageModelChatMessageRole.User ? "user" : "assistant";
}

function flattenContent(content: readonly unknown[]): string {
  const bits: string[] = [];
  for (const part of content) {
    if (part instanceof vscode.LanguageModelTextPart) bits.push(part.value);
    else if (part && typeof part === "object" && "value" in part) bits.push(String((part as { value: unknown }).value));
  }
  return bits.join("");
}

class LocalChatProvider implements vscode.LanguageModelChatProvider {
  private readonly _onChange = new vscode.EventEmitter<void>();
  readonly onDidChangeLanguageModelChatInformation = this._onChange.event;

  refresh(): void {
    this._onChange.fire();
  }

  provideLanguageModelChatInformation(): vscode.LanguageModelChatInformation[] {
    return configured().map((m) => ({
      id: `${m.backend}:${m.model}`,
      name: m.name,
      family: m.backend,
      version: "1",
      maxInputTokens: 8192,
      maxOutputTokens: 4096,
      tooltip: `${m.backend} @ ${m.baseUrl}`,
      detail: m.baseUrl,
      capabilities: { toolCalling: true },
    }));
  }

  async provideLanguageModelChatResponse(
    model: vscode.LanguageModelChatInformation,
    messages: readonly vscode.LanguageModelChatRequestMessage[],
    _options: vscode.ProvideLanguageModelChatResponseOptions,
    progress: vscode.Progress<vscode.LanguageModelResponsePart>,
    token: vscode.CancellationToken,
  ): Promise<void> {
    const saved = configured().find((m) => `${m.backend}:${m.model}` === model.id);
    if (!saved) throw new Error(`Unknown local model ${model.id}`);
    const body = {
      model: saved.model,
      stream: true,
      messages: messages.map((m) => ({
        role: roleOf(m.role),
        content: flattenContent(m.content),
      })),
    };
    const ac = new AbortController();
    const stop = token.onCancellationRequested(() => ac.abort());
    try {
      const res = await fetch(`${saved.baseUrl.replace(/\/$/, "")}/chat/completions`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
        signal: ac.signal,
      });
      if (!res.ok || !res.body) {
        const err = await res.text().catch(() => res.statusText);
        throw new Error(`${saved.backend} ${res.status}: ${err.slice(0, 400)}`);
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        const lines = buf.split("\n");
        buf = lines.pop() ?? "";
        for (const line of lines) {
          const s = line.trim();
          if (!s.startsWith("data:")) continue;
          const data = s.slice(5).trim();
          if (data === "[DONE]") return;
          try {
            const json = JSON.parse(data) as { choices?: { delta?: { content?: string } }[] };
            const piece = json.choices?.[0]?.delta?.content;
            if (piece) progress.report(new vscode.LanguageModelTextPart(piece));
          } catch { /* ignore keepalives */ }
        }
      }
    } finally {
      stop.dispose();
    }
  }

  provideTokenCount(
    _model: vscode.LanguageModelChatInformation,
    text: string | vscode.LanguageModelChatRequestMessage,
  ): Thenable<number> {
    const s = typeof text === "string" ? text : flattenContent(text.content);
    return Promise.resolve(Math.max(1, Math.ceil(s.length / 4)));
  }
}

export function registerLocalModels(context: vscode.ExtensionContext): void {
  const provider = new LocalChatProvider();
  context.subscriptions.push(
    vscode.commands.registerCommand("switchbay.localModels", () => configureLocalModels()),
    vscode.workspace.onDidChangeConfiguration((e) => {
      if (e.affectsConfiguration("switchbay.localModels")) provider.refresh();
    }),
  );
  if (typeof vscode.lm.registerLanguageModelChatProvider === "function") {
    context.subscriptions.push(vscode.lm.registerLanguageModelChatProvider(VENDOR, provider));
  }
}
