/**
 * Pure helpers for Mode B wiki pointers and CE figure paths.
 * No vscode import — unit-tested with node:test.
 */
import * as path from "path";

export type CuriosityPointer = {
  workspace: string;
  project?: string;
  projectKind?: string;
};

export type CeWorkspaceMarks = {
  hasWikiDir: boolean;
  hasCuratorConfig: boolean;
  hasWikiGit: boolean;
};

export const IMAGE_EXTS = new Set([
  ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".avif",
]);

const IMAGE_WIKILINK_RE = /!\[\[([^\]|]+)(?:\|([^\]]*))?\]\]/g;
const MD_IMAGE_RE = /!\[([^\]]*)\]\(([^)]+)\)/g;

export function looksLikeCeWorkspace(marks: CeWorkspaceMarks): boolean {
  return marks.hasWikiDir || marks.hasCuratorConfig || marks.hasWikiGit;
}

const VISION_RE = /gpt-4o|gpt-4\.1|gpt-5|gpt-4-turbo|claude|gemini|gemma-?3|llava|pixtral|qwen.*vl|vision/;
const NOT_VISION_RE = /gpt-3\.5|text-embedding|whisper|tts|davinci|instruct|codex-mini/;

/** Heuristic when vscode.lm does not expose capabilities.imageInput. */
export function looksLikeVisionModel(id: string, family = "", name = ""): boolean {
  const blob = `${id} ${family} ${name}`.toLowerCase();
  if (NOT_VISION_RE.test(blob)) return false;
  return VISION_RE.test(blob);
}

/** `@switchbay /sbh on|off` — empty/unknown means show the picker. */
export function parseSbhArg(prompt: string): "on" | "off" | "ask" {
  const t = prompt.trim().toLowerCase();
  if (!t) return "ask";
  if (["on", "enable", "enabled", "1", "true"].includes(t)) return "on";
  if (["off", "disable", "disabled", "0", "false"].includes(t)) return "off";
  return "ask";
}

export function expandUserPath(raw: string, home: string): string {
  const t = raw.trim();
  if (t === "~") return home;
  if (t.startsWith("~/")) return home + t.slice(1);
  if (t.startsWith("$HOME/") || t.startsWith("${HOME}/")) {
    return home + t.slice(t.indexOf("/"));
  }
  return t;
}

function unquoteToml(v: string): string {
  const t = v.trim();
  if (t.length >= 2) {
    if ((t.startsWith('"') && t.endsWith('"')) || (t.startsWith("'") && t.endsWith("'"))) {
      return t.slice(1, -1).replace(/\\"/g, '"').replace(/\\\\/g, "\\");
    }
  }
  return t;
}

/** Minimal pointer-file parser (CE `code_repo.py` schema, top-level keys). */
export function parseCuriosityConfig(text: string): CuriosityPointer | null {
  let workspace = "";
  let project: string | undefined;
  let projectKind: string | undefined;
  let section = "";
  for (const raw of text.split(/\r?\n/)) {
    const hash = raw.indexOf("#");
    const line = (hash >= 0 && !inQuotes(raw, hash) ? raw.slice(0, hash) : raw).trim();
    if (!line) continue;
    const sec = line.match(/^\[([A-Za-z0-9_.-]+)\]$/);
    if (sec) {
      section = sec[1];
      continue;
    }
    if (section) continue;
    const kv = line.match(/^([A-Za-z_][\w]*)\s*=\s*(.*)$/);
    if (!kv) continue;
    const key = kv[1];
    const val = unquoteToml(kv[2]);
    if (key === "workspace") workspace = val;
    else if (key === "project") project = val;
    else if (key === "project_kind") projectKind = val;
  }
  if (!workspace) return null;
  return { workspace, project, projectKind };
}

function inQuotes(line: string, at: number): boolean {
  let q: '"' | "'" | null = null;
  for (let i = 0; i < at; i++) {
    const c = line[i];
    if (q) {
      if (c === q && line[i - 1] !== "\\") q = null;
    } else if (c === '"' || c === "'") {
      q = c;
    }
  }
  return q != null;
}

export function isImageRef(target: string): boolean {
  const bare = target.trim().split(/[?#]/)[0] || "";
  const dot = bare.lastIndexOf(".");
  if (dot < 0) return false;
  return IMAGE_EXTS.has(bare.slice(dot).toLowerCase());
}

export type MdImage = { alt: string; src: string };

/** Obsidian `![[file.png]]` plus markdown `![alt](src)`. */
export function extractMarkdownImages(md: string): MdImage[] {
  const out: MdImage[] = [];
  IMAGE_WIKILINK_RE.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = IMAGE_WIKILINK_RE.exec(md))) {
    const src = (m[1] || "").trim();
    if (!isImageRef(src)) continue;
    out.push({ alt: (m[2] || "").trim(), src });
  }
  MD_IMAGE_RE.lastIndex = 0;
  while ((m = MD_IMAGE_RE.exec(md))) {
    const src = (m[2] || "").trim();
    if (!src || src.startsWith("data:")) continue;
    out.push({ alt: (m[1] || "").trim(), src });
  }
  return out;
}

/** Rewrite image wikilinks to markdown images so a tiny MD renderer can see them. */
export function expandImageWikilinks(md: string): string {
  return md.replace(IMAGE_WIKILINK_RE, (full, target: string, display?: string) => {
    const src = String(target || "").trim();
    if (!isImageRef(src)) return full;
    const alt = String(display || "").trim();
    return `![${alt}](${src})`;
  });
}

/**
 * Filesystem candidates for a wiki image src.
 * `pageDir` is the markdown file's directory; `wikiRoot` is the CE workspace.
 */
export function candidateImagePaths(src: string, pageDir: string, wikiRoot: string): string[] {
  const cleaned = src.replace(/^["']|["']$/g, "").replace(/^\.\//, "").split(/[?#]/)[0] || "";
  if (!cleaned || cleaned.includes("..")) return [];
  const base = path.basename(cleaned);
  const posix = cleaned.replace(/\\/g, "/");
  const join = (root: string, rel: string) => path.join(root, ...rel.split("/").filter((p) => p && p !== "."));
  const out: string[] = [];
  const add = (p: string) => {
    if (p && !out.includes(p)) out.push(p);
  };
  if (path.isAbsolute(cleaned)) add(cleaned);
  add(join(pageDir, posix));
  add(join(wikiRoot, posix));
  add(join(wikiRoot, "wiki/" + posix));
  if (posix.startsWith("figures/")) add(join(wikiRoot, "wiki/" + posix));
  add(join(wikiRoot, "wiki/figures/" + posix));
  add(join(wikiRoot, "wiki/figures/_assets/" + posix));
  add(join(wikiRoot, "wiki/figures/_assets/" + base));
  add(join(pageDir, "_assets/" + base));
  return out;
}
