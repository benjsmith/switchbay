/**
 * Pasting an image into the rail (or Zen) composer. The bytes go
 * through the same POST /api/chat/upload the attach button uses, and
 * the message is sent with the same `[attached: <path>]` lines. Plain
 * text paste is not handled here — the textarea keeps its own insert.
 */

export const CHAT_UPLOAD_URL = "/api/chat/upload";

const IMAGE_EXT = /\.(png|jpe?g|gif|webp|bmp|avif|heic|heif|tiff?|svg)$/i;

const MIME_EXT: Record<string, string> = {
  "image/png": "png",
  "image/jpeg": "jpg",
  "image/jpg": "jpg",
  "image/gif": "gif",
  "image/webp": "webp",
  "image/bmp": "bmp",
  "image/avif": "avif",
  "image/heic": "heic",
  "image/heif": "heif",
  "image/tiff": "tiff",
  "image/svg+xml": "svg",
  "image/x-icon": "ico",
};

export type ClipboardItemLike = {
  kind: string;
  type: string;
  getAsFile?: () => File | null;
};

export type ClipboardLike = {
  files?: ArrayLike<File> | null;
  items?: ArrayLike<ClipboardItemLike> | null;
  getData?: (format: string) => string;
};

export type ComposerSelection = {
  value: string;
  selectionStart: number;
  selectionEnd: number;
};

export type PasteResult =
  | { kind: "text" }
  | { kind: "images"; files: File[]; value: string; cursor: number };

export type AttachmentRef = {
  status: string;
  path: string | null;
};

export type SubmitPlan =
  | { blocked: true }
  | { blocked: false; message: string | null };

export function isImageFile(file: File): boolean {
  const type = (file.type || "").toLowerCase();
  if (type.startsWith("image/")) return true;
  if (!type && IMAGE_EXT.test(file.name)) return true;
  return false;
}

function listOf<T>(value: ArrayLike<T> | null | undefined): T[] {
  if (!value || typeof value.length !== "number") return [];
  const out: T[] = [];
  for (let i = 0; i < value.length; i++) {
    const item = value[i];
    if (item !== undefined) out.push(item);
  }
  return out;
}

function withItemType(file: File, itemType: string): File {
  if (file.type || !itemType.startsWith("image/")) return file;
  return new File([file], file.name, { type: itemType, lastModified: file.lastModified });
}

/** Image files on a paste clipboard. Browsers often list the same
 *  paste in both `files` and `items`; when `files` has images, that
 *  list is the one we keep. `items` covers browsers that only put
 *  the image there. */
export function clipboardImages(clipboard: ClipboardLike | null): File[] {
  if (!clipboard) return [];
  const fromFiles = listOf(clipboard.files).filter(isImageFile);
  if (fromFiles.length > 0) return fromFiles;
  const fromItems: File[] = [];
  for (const item of listOf(clipboard.items)) {
    if (item.kind !== "file") continue;
    const type = (item.type || "").toLowerCase();
    if (type && !type.startsWith("image/")) continue;
    let file: File | null = null;
    try {
      file = item.getAsFile?.() ?? null;
    } catch {
      file = null;
    }
    if (!file) continue;
    file = withItemType(file, type);
    if (type.startsWith("image/") || isImageFile(file)) fromItems.push(file);
  }
  return fromItems;
}

function clamp(n: number, lo: number, hi: number): number {
  if (!Number.isFinite(n)) return lo;
  return Math.min(hi, Math.max(lo, n));
}

function clipboardText(clipboard: ClipboardLike): string {
  try {
    return clipboard.getData?.("text/plain") ?? "";
  } catch {
    return "";
  }
}

/** `kind: "text"` means the caller must not call preventDefault.
 *  `kind: "images"` is one or more images, plus any plain text that
 *  came with them inserted at the selection. */
export function applyImagePaste(
  clipboard: ClipboardLike | null,
  composer: ComposerSelection,
): PasteResult {
  const files = clipboardImages(clipboard);
  if (files.length === 0 || !clipboard) return { kind: "text" };
  const raw = clipboardText(clipboard);
  if (!raw.trim()) {
    const cursor = clamp(composer.selectionStart, 0, composer.value.length);
    return { kind: "images", files, value: composer.value, cursor };
  }
  const start = clamp(composer.selectionStart, 0, composer.value.length);
  const end = clamp(composer.selectionEnd, start, composer.value.length);
  const value = composer.value.slice(0, start) + raw + composer.value.slice(end);
  return { kind: "images", files, value, cursor: start + raw.length };
}

/** Filename the upload stores. A screenshot with no name becomes
 *  `pasted-image.png` (or the matching extension) so the agent can
 *  tell it is an image. */
export function uploadName(file: File): string {
  const name = file.name.trim();
  if (name && name !== "blob") return name;
  const ext = MIME_EXT[(file.type || "").toLowerCase()] ?? "png";
  return `pasted-image.${ext}`;
}

export function fileForUpload(file: File): File {
  const name = uploadName(file);
  if (name === file.name) return file;
  return new File([file], name, {
    type: file.type || "image/png",
    lastModified: file.lastModified,
  });
}

export async function uploadChatAttachment(
  file: File,
  fetchImpl: typeof fetch = fetch,
): Promise<{ path: string; size: number; filename: string }> {
  const named = fileForUpload(file);
  const body = new FormData();
  body.append("file", named, named.name);
  const response = await fetchImpl(CHAT_UPLOAD_URL, { method: "POST", body });
  let payload: { path?: unknown; size?: unknown; filename?: unknown; error?: unknown } = {};
  try {
    payload = (await response.json()) as typeof payload;
  } catch {
    payload = {};
  }
  if (!response.ok || typeof payload.path !== "string" || payload.path.length === 0) {
    const reason = typeof payload.error === "string" && payload.error
      ? payload.error
      : String(response.status);
    throw new Error(reason);
  }
  const size = typeof payload.size === "number" ? payload.size : named.size;
  const filename = typeof payload.filename === "string" && payload.filename
    ? payload.filename
    : named.name;
  return { path: payload.path, size, filename };
}

export function readyAttachmentPaths(items: readonly AttachmentRef[]): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  for (const item of items) {
    if (item.status !== "ready" || !item.path) continue;
    const path = item.path.trim();
    if (!path || seen.has(path)) continue;
    seen.add(path);
    out.push(path);
  }
  return out;
}

/** True while a pasted image still belongs to the unsent message
 *  (uploading or ready). A failed upload does not. */
export function attachmentsPending(items: readonly { status: string }[]): boolean {
  return items.some((item) => item.status === "uploading" || item.status === "ready");
}

export function composeOutgoing(text: string, paths: readonly string[]): string {
  const lines: string[] = [];
  const seen = new Set<string>();
  for (const raw of paths) {
    const path = raw.trim();
    if (!path || seen.has(path)) continue;
    seen.add(path);
    lines.push(`[attached: ${path}]`);
  }
  const body = text.trim();
  if (lines.length === 0) return body;
  if (!body) return lines.join("\n");
  return `${lines.join("\n")}\n${body}`;
}

/** Build the string the rail submits. An attached image is chat, so
 *  a draft that would otherwise run as a shell command is sent as
 *  the message plus its `[attached:]` lines. `null` means nothing
 *  to send. */
export function messageForSubmit(
  text: string,
  paths: readonly string[],
  asShell: boolean,
): string | null {
  const attached = paths.some((path) => path.trim().length > 0);
  const body = composeOutgoing(text, paths);
  if (!body) return null;
  if (attached) return body;
  return asShell ? `!${body}` : body;
}

export function planComposerSubmit(
  text: string,
  attachments: readonly AttachmentRef[],
  asShell: boolean,
): SubmitPlan {
  if (attachments.some((item) => item.status === "uploading")) return { blocked: true };
  return {
    blocked: false,
    message: messageForSubmit(text, readyAttachmentPaths(attachments), asShell),
  };
}
