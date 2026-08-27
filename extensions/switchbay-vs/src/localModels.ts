/**
 * Settings-like helper: discover / install local MLX, llama.cpp, and
 * Ollama backends, persist them in VS Code config, and publish them
 * as chat models (LanguageModelChatProvider) so Agents/Chat can use
 * them without the Switch Bay daemon.
 */
import * as cp from "child_process";
import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as vscode from "vscode";
import { looksLikeVisionModel } from "./wikiPointer";

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

const EXTRA_BIN_DIRS = [
  path.join(os.homedir(), ".local", "bin"),
  path.join(os.homedir(), ".cargo", "bin"),
  "/opt/homebrew/bin",
  "/usr/local/bin",
];

function which(names: string[]): string | undefined {
  const pathEnv = process.env.PATH || "";
  const dirs = [...pathEnv.split(path.delimiter).filter(Boolean), ...EXTRA_BIN_DIRS];
  for (const name of names) {
    if (path.isAbsolute(name) && fs.existsSync(name)) return name;
    for (const dir of dirs) {
      const cand = path.join(dir, name);
      if (fs.existsSync(cand)) {
        try {
          fs.accessSync(cand, fs.constants.X_OK);
          return cand;
        } catch { /* not executable */ }
      }
    }
  }
  return undefined;
}

function execCapture(bin: string, args: string[], timeoutMs = 8000): Promise<string> {
  return new Promise((resolve) => {
    const child = cp.spawn(bin, args, { env: process.env });
    let out = "";
    const t = setTimeout(() => {
      child.kill();
      resolve(out);
    }, timeoutMs);
    child.stdout?.on("data", (b: Buffer) => { out += b.toString(); });
    child.stderr?.on("data", (b: Buffer) => { out += b.toString(); });
    child.on("close", () => {
      clearTimeout(t);
      resolve(out);
    });
    child.on("error", () => {
      clearTimeout(t);
      resolve(out);
    });
  });
}

function spawnDetached(bin: string, args: string[]): void {
  const child = cp.spawn(bin, args, {
    detached: true,
    stdio: "ignore",
    env: process.env,
  });
  child.unref();
}

async function waitForJson(url: string, attempts = 10, delayMs = 700): Promise<unknown | null> {
  for (let i = 0; i < attempts; i++) {
    const body = await fetchJson(url, 1500);
    if (body) return body;
    await new Promise((r) => setTimeout(r, delayMs));
  }
  return null;
}

function openaiModelIds(body: unknown): string[] {
  const data = (body as { data?: { id?: string }[] } | null)?.data;
  if (!Array.isArray(data)) return [];
  return data.map((m) => m.id || "").filter(Boolean);
}

function walkFiles(root: string, pred: (name: string) => boolean, max = 80): string[] {
  const out: string[] = [];
  const walk = (dir: string, depth: number) => {
    if (out.length >= max || depth > 6) return;
    let entries: fs.Dirent[];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      if (out.length >= max) return;
      if (e.name.startsWith(".")) continue;
      const full = path.join(dir, e.name);
      if (e.isDirectory()) walk(full, depth + 1);
      else if (pred(e.name)) out.push(full);
    }
  };
  if (fs.existsSync(root)) walk(root, 0);
  return out;
}

function switchbayModelsDir(): string {
  const home = os.homedir();
  if (process.platform === "darwin") return path.join(home, "Library", "Application Support", "switchbay", "models");
  if (process.platform === "win32") {
    const base = process.env.LOCALAPPDATA || path.join(home, "AppData", "Local");
    return path.join(base, "switchbay", "models");
  }
  const base = process.env.XDG_STATE_HOME || path.join(home, ".local", "state");
  return path.join(base, "switchbay", "models");
}

function hfHubRoot(): string {
  return process.env.HF_HOME
    ? path.join(process.env.HF_HOME, "hub")
    : path.join(os.homedir(), ".cache", "huggingface", "hub");
}

function listGgufOnDisk(): string[] {
  const roots = [
    switchbayModelsDir(),
    path.join(os.homedir(), "models"),
    path.join(os.homedir(), ".llama.cpp"),
    hfHubRoot(),
  ];
  const files = new Set<string>();
  for (const root of roots) {
    for (const f of walkFiles(root, (n) => n.toLowerCase().endsWith(".gguf"), 40)) {
      files.add(f);
    }
  }
  return [...files];
}

function repoIdFromHfDir(dirName: string): string | null {
  // models--mlx-community--Qwen3-4bit
  if (!dirName.startsWith("models--")) return null;
  const rest = dirName.slice("models--".length);
  const parts = rest.split("--");
  if (parts.length < 2) return null;
  return `${parts[0]}/${parts.slice(1).join("--")}`;
}

function listMlxOnDisk(): string[] {
  const ids = new Set<string>();
  const serveRoot = path.join(os.homedir(), ".mlx-serve", "models");
  if (fs.existsSync(serveRoot)) {
    for (const org of fs.readdirSync(serveRoot, { withFileTypes: true })) {
      if (!org.isDirectory()) continue;
      const orgDir = path.join(serveRoot, org.name);
      let repos: fs.Dirent[] = [];
      try { repos = fs.readdirSync(orgDir, { withFileTypes: true }); } catch { continue; }
      for (const repo of repos) {
        if (repo.isDirectory()) ids.add(`${org.name}/${repo.name}`);
      }
    }
  }
  const hub = hfHubRoot();
  if (fs.existsSync(hub)) {
    let entries: fs.Dirent[] = [];
    try { entries = fs.readdirSync(hub, { withFileTypes: true }); } catch { entries = []; }
    for (const e of entries) {
      if (!e.isDirectory()) continue;
      const id = repoIdFromHfDir(e.name);
      if (!id) continue;
      const lower = id.toLowerCase();
      if (lower.includes("mlx") || lower.includes("4bit") || lower.includes("8bit")) {
        ids.add(id);
      }
    }
  }
  return [...ids];
}

async function mlxServeList(bin: string): Promise<string[]> {
  const text = await execCapture(bin, ["list"], 8000);
  const models: string[] = [];
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("NAME") || /^-+$/.test(t)) continue;
    const id = t.split(/\s+/)[0];
    if (id.includes("/") || id.includes(":") || /^[A-Za-z0-9._-]+$/.test(id)) {
      if (!/^(list|serve|pull|run|NAME|model)$/i.test(id)) models.push(id);
    }
  }
  return [...new Set(models)];
}

async function probeOpenAiPorts(ports: number[]): Promise<{ port: number; models: string[] } | null> {
  for (const port of ports) {
    const body = await fetchJson(`http://127.0.0.1:${port}/v1/models`, 1200);
    const models = openaiModelIds(body);
    if (body) return { port, models };
  }
  return null;
}

async function ensureMlxServe(bin: string | undefined): Promise<{ port: number; models: string[] } | null> {
  const live = await probeOpenAiPorts([11234, 8888, 8889, 8890, 8891, 8892]);
  if (live) return live;
  if (!bin) return null;
  const modelDir = path.join(os.homedir(), ".mlx-serve", "models");
  spawnDetached(bin, ["--serve", "--host", "127.0.0.1", "--port", "11234", "--model-dir", modelDir]);
  const body = await waitForJson("http://127.0.0.1:11234/v1/models", 12, 800);
  if (body) return { port: 11234, models: openaiModelIds(body) };
  spawnDetached(bin, ["serve"]);
  const again = await waitForJson("http://127.0.0.1:11234/v1/models", 8, 800);
  if (again) return { port: 11234, models: openaiModelIds(again) };
  return null;
}

async function ensureLlamaServer(bin: string | undefined, gguf?: string): Promise<{ port: number; models: string[] } | null> {
  const live = await probeOpenAiPorts([8080, 8878, 8879, 8880]);
  if (live) return live;
  if (!bin || !gguf) return null;
  spawnDetached(bin, ["-m", gguf, "--host", "127.0.0.1", "--port", "8080", "-c", "8192"]);
  const body = await waitForJson("http://127.0.0.1:8080/v1/models", 15, 800);
  if (body) return { port: 8080, models: openaiModelIds(body) };
  return null;
}

export function listConfiguredLocalModels(): LocalModel[] {
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

export type LocalProbe = { backend: LocalBackend; ok: boolean; models: string[]; hint: string };

export async function probeLocalBackends(opts?: { start?: boolean }): Promise<LocalProbe[]> {
  const ollama = await fetchJson("http://127.0.0.1:11434/api/tags");
  const ollamaModels = Array.isArray((ollama as { models?: { name?: string }[] } | null)?.models)
    ? (ollama as { models: { name?: string }[] }).models.map((m) => m.name || "").filter(Boolean)
    : [];

  const llamaBin = which(["llama-server"]);
  const mlxServeBin = which(["mlx-serve"]);
  const mlxLmBin = which(["mlx_lm.server", "mlx-lm"]);
  const ggufs = listGgufOnDisk();
  const mlxDisk = listMlxOnDisk();

  const llamaLive = await probeOpenAiPorts([8080, 8878, 8879, 8880]);
  const llamaModels = [
    ...(llamaLive?.models ?? []),
    ...ggufs.map((f) => f),
  ].filter((v, i, a) => a.indexOf(v) === i);

  let mlxModels: string[] = [];
  let mlxOk = false;
  let mlxHint = "MLX is Apple silicon only.";
  if (process.platform === "darwin" && os.arch() === "arm64") {
    if (mlxServeBin) {
      mlxModels.push(...await mlxServeList(mlxServeBin));
      if (opts?.start) {
        const started = await ensureMlxServe(mlxServeBin);
        if (started) {
          mlxOk = true;
          mlxModels.push(...started.models.map((id) => `${id} (:${started.port})`));
        }
      }
    }
    const live = await probeOpenAiPorts([11234, 8888, 8889, 8890, 8891, 8892]);
    if (live) {
      mlxOk = true;
      mlxModels.push(...live.models.map((id) => `${id} (:${live.port})`));
    }
    mlxModels.push(...mlxDisk);
    mlxModels = [...new Set(mlxModels)];
    const binLabel = mlxServeBin ? "mlx-serve" : mlxLmBin ? "mlx_lm.server" : "not on PATH";
    mlxHint = mlxOk
      ? `${mlxModels.length} model(s) (${binLabel})`
      : mlxServeBin || mlxLmBin
        ? `${mlxModels.length ? mlxModels.length + " on disk; " : ""}binary found (${binLabel}) but no server answered. Pull a tag or start mlx-serve serve.`
        : "Not found. `uv tool install mlx-lm` or install mlx-serve, then pull a tag.";
  }

  const llamaOk = Boolean(llamaLive) || llamaModels.length > 0;
  const llamaHint = llamaLive
    ? `${llamaModels.length || "server"} on :${llamaLive.port}`
    : llamaBin
      ? `${ggufs.length} GGUF on disk; llama-server at ${llamaBin}`
      : ggufs.length
        ? `${ggufs.length} GGUF on disk; llama-server not on PATH`
        : "Not running. `brew install llama.cpp`, pull a GGUF tag, then llama-server -m <file> --port 8080.";

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
      ok: llamaOk,
      models: llamaModels,
      hint: llamaHint,
    },
    {
      backend: "mlx",
      ok: mlxOk || mlxModels.length > 0,
      models: mlxModels,
      hint: mlxHint,
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
  let probes: LocalProbe[];
  try {
    probes = await probeLocalBackends({ start: true });
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
      const shown = name.includes(path.sep) ? path.basename(name) : name;
      picks.push({
        label: `    $(add) ${shown}`,
        description: `Add ${DEFAULTS[p.backend].label} model to VS Code`,
        detail: `${p.backend}\t${name}`,
      });
    }
  }
  picks.push({ label: "", kind: vscode.QuickPickItemKind.Separator });
  picks.push({ label: "$(cloud-download) Pull an Ollama tag…", description: "ollama pull <tag>" });
  picks.push({ label: "$(cloud-download) Pull a llama.cpp GGUF…", description: "Hugging Face repo, e.g. bartowski/Qwen2.5-7B-Instruct-GGUF" });
  if (process.platform === "darwin" && os.arch() === "arm64") {
    picks.push({ label: "$(cloud-download) Pull an MLX tag…", description: "mlx-serve pull <tag> or mlx-community/<repo>" });
  }
  picks.push({ label: "$(link-external) Install Ollama…", description: "Open ollama.com/download" });
  if (process.platform === "darwin" && os.arch() === "arm64") {
    picks.push({ label: "$(link-external) MLX install hint", description: "uv tool install mlx-lm · or mlx-serve" });
  }
  picks.push({ label: "$(server) llama.cpp install hint", description: "brew install llama.cpp" });
  const saved = listConfiguredLocalModels();
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
  if (choice.label.includes("Pull a llama.cpp")) {
    const tag = await vscode.window.showInputBox({
      title: "Pull llama.cpp GGUF",
      placeHolder: "bartowski/Qwen2.5-7B-Instruct-GGUF",
      prompt: "Hugging Face repo (owner/name). Downloads into Switch Bay's models dir via huggingface-cli, or llama-server -hf.",
    });
    if (!tag) return;
    const dest = switchbayModelsDir();
    fs.mkdirSync(dest, { recursive: true });
    const llama = which(["llama-server"]);
    const hf = which(["huggingface-cli", "hf"]);
    const term = vscode.window.createTerminal({ name: "llama.cpp pull" });
    term.show();
    const quotedDest = JSON.stringify(dest);
    const quotedTag = JSON.stringify(tag);
    if (hf) {
      term.sendText(`mkdir -p ${quotedDest} && ${JSON.stringify(hf)} download ${quotedTag} --local-dir ${quotedDest} --include '*.gguf'`);
    } else if (llama) {
      term.sendText(`${JSON.stringify(llama)} -hf ${quotedTag} --host 127.0.0.1 --port 8080`);
    } else {
      term.sendText(`echo "Install huggingface-cli (pip install huggingface_hub) or llama-server (brew install llama.cpp). Repo: ${tag}"`);
    }
    return;
  }
  if (choice.label.includes("Pull an MLX")) {
    const tag = await vscode.window.showInputBox({
      title: "Pull MLX model",
      placeHolder: "mlx-community/Qwen3-4B-4bit",
      prompt: "mlx-serve tag or Hugging Face repo (mlx-community/…). Uses mlx-serve pull when installed.",
    });
    if (!tag) return;
    const mlxServe = which(["mlx-serve"]);
    const hf = which(["huggingface-cli", "hf"]);
    const term = vscode.window.createTerminal({ name: "MLX pull" });
    term.show();
    if (mlxServe) {
      term.sendText(`${JSON.stringify(mlxServe)} pull ${JSON.stringify(tag)}`);
    } else if (hf) {
      const repo = tag.includes("/") ? tag : `mlx-community/${tag}`;
      term.sendText(`${JSON.stringify(hf)} download ${JSON.stringify(repo)}`);
    } else {
      term.sendText(`echo "Install mlx-serve or huggingface-cli. Then: mlx-serve pull ${tag}"`);
    }
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

  const [backendRaw, payload] = (choice.detail || "").split("\t");
  const backend = backendRaw as LocalBackend;
  if (!backend || !(backend in DEFAULTS)) return;
  const rawName = (payload || choice.label.replace(/^\s*\$\([^)]+\)\s*/, "").trim()).trim();
  const model = path.basename(rawName).replace(/\s*\(:\d+\)\s*$/, "");
  if (backend === "llamacpp" && rawName.endsWith(".gguf")) {
    const llama = which(["llama-server"]);
    await vscode.window.withProgress(
      { location: vscode.ProgressLocation.Notification, title: `Starting llama-server with ${model}…` },
      async () => { await ensureLlamaServer(llama, rawName); },
    );
  }
  if (backend === "mlx") {
    const mlxServe = which(["mlx-serve"]);
    if (mlxServe) {
      await vscode.window.withProgress(
        { location: vscode.ProgressLocation.Notification, title: "Starting mlx-serve…" },
        async () => { await ensureMlxServe(mlxServe); },
      );
    }
  }
  const next: LocalModel = {
    backend,
    name: `${DEFAULTS[backend].label} · ${model}`,
    model,
    baseUrl: baseUrlFor(backend, rawName),
  };
  if (backend === "mlx") {
    const live = await probeOpenAiPorts([11234, 8888, 8889, 8890]);
    if (live) next.baseUrl = `http://127.0.0.1:${live.port}/v1`;
  }
  if (backend === "llamacpp") {
    const live = await probeOpenAiPorts([8080, 8878, 8879]);
    if (live) next.baseUrl = `http://127.0.0.1:${live.port}/v1`;
  }
  const models = listConfiguredLocalModels().filter((m) => !(m.backend === next.backend && m.model === next.model));
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

type OpenAiContent =
  | string
  | Array<{ type: "text"; text: string } | { type: "image_url"; image_url: { url: string } }>;

function openaiContent(content: readonly unknown[]): OpenAiContent {
  const parts: Array<{ type: "text"; text: string } | { type: "image_url"; image_url: { url: string } }> = [];
  let sawImage = false;
  for (const part of content) {
    if (part instanceof vscode.LanguageModelTextPart) {
      parts.push({ type: "text", text: part.value });
      continue;
    }
    if (part instanceof vscode.LanguageModelDataPart && /^image\//.test(part.mimeType)) {
      sawImage = true;
      const b64 = Buffer.from(part.data).toString("base64");
      parts.push({ type: "image_url", image_url: { url: `data:${part.mimeType};base64,${b64}` } });
      continue;
    }
    if (part && typeof part === "object" && "value" in part) {
      parts.push({ type: "text", text: String((part as { value: unknown }).value) });
    }
  }
  if (!sawImage) return flattenContent(content);
  return parts;
}

class LocalChatProvider implements vscode.LanguageModelChatProvider {
  private readonly _onChange = new vscode.EventEmitter<void>();
  readonly onDidChangeLanguageModelChatInformation = this._onChange.event;

  refresh(): void {
    this._onChange.fire();
  }

  provideLanguageModelChatInformation(): vscode.LanguageModelChatInformation[] {
    return listConfiguredLocalModels().map((m) => ({
      id: `${m.backend}:${m.model}`,
      name: m.name,
      family: m.backend,
      version: "1",
      maxInputTokens: 8192,
      maxOutputTokens: 4096,
      tooltip: `${m.backend} @ ${m.baseUrl}`,
      detail: m.baseUrl,
      capabilities: {
        toolCalling: true,
        imageInput: looksLikeVisionModel(m.model, m.backend, m.name),
      },
    }));
  }

  async provideLanguageModelChatResponse(
    model: vscode.LanguageModelChatInformation,
    messages: readonly vscode.LanguageModelChatRequestMessage[],
    _options: vscode.ProvideLanguageModelChatResponseOptions,
    progress: vscode.Progress<vscode.LanguageModelResponsePart>,
    token: vscode.CancellationToken,
  ): Promise<void> {
    const saved = listConfiguredLocalModels().find((m) => `${m.backend}:${m.model}` === model.id);
    if (!saved) throw new Error(`Unknown local model ${model.id}`);
    const body = {
      model: saved.model,
      stream: true,
      messages: messages.map((m) => ({
        role: roleOf(m.role),
        content: openaiContent(m.content),
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
