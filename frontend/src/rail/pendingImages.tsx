import { useEffect, useState, type ClipboardEvent } from "react";
import {
  applyImagePaste,
  uploadChatAttachment,
  uploadName,
} from "../lib/imagePaste";

export type PendingImage = {
  id: string;
  name: string;
  previewUrl: string;
  status: "uploading" | "ready" | "error";
  path: string | null;
  error?: string;
};

let items: PendingImage[] = [];
const listeners = new Set<(snap: PendingImage[]) => void>();

function emit(): void {
  const snap = items;
  for (const listener of listeners) listener(snap);
}

function nextId(): string {
  try {
    if (typeof crypto !== "undefined" && typeof crypto.randomUUID === "function") {
      return crypto.randomUUID();
    }
  } catch {
    /* insecure context */
  }
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

function patch(id: string, partial: Partial<PendingImage>): void {
  let changed = false;
  items = items.map((item) => {
    if (item.id !== id) return item;
    changed = true;
    return { ...item, ...partial };
  });
  if (changed) emit();
}

/** Shared by the Power rail and the Zen composer so a pasted image
 *  survives a mode switch the same way the unsent text does. */
export function usePendingImages(): PendingImage[] {
  const [list, setList] = useState(items);
  useEffect(() => {
    const listener = (snap: PendingImage[]) => setList(snap);
    listeners.add(listener);
    setList(items);
    return () => {
      listeners.delete(listener);
    };
  }, []);
  return list;
}

export function addPastedImages(files: readonly File[]): void {
  for (const file of files) {
    const id = nextId();
    const name = uploadName(file);
    const previewUrl = URL.createObjectURL(file);
    items = [...items, { id, name, previewUrl, status: "uploading", path: null }];
    emit();
    void uploadChatAttachment(file)
      .then((body) => {
        patch(id, { status: "ready", path: body.path, name: body.filename || name });
      })
      .catch((err: unknown) => {
        const message = err instanceof Error ? err.message : "upload failed";
        patch(id, { status: "error", error: message });
      });
  }
}

export function removePendingImage(id: string): void {
  const item = items.find((it) => it.id === id);
  if (!item) return;
  URL.revokeObjectURL(item.previewUrl);
  items = items.filter((it) => it.id !== id);
  emit();
}

export function clearPendingImages(): void {
  if (items.length === 0) return;
  for (const item of items) URL.revokeObjectURL(item.previewUrl);
  items = [];
  emit();
}

/** Text paste returns immediately, so the textarea handles it.
 *  An image paste is prevented and attached. */
export function onComposerPaste(
  ev: ClipboardEvent<HTMLTextAreaElement>,
  setInput: (value: string) => void,
): void {
  const data = ev.clipboardData;
  if (!data) return;
  const el = ev.currentTarget;
  const result = applyImagePaste(data, {
    value: el.value,
    selectionStart: el.selectionStart ?? 0,
    selectionEnd: el.selectionEnd ?? 0,
  });
  if (result.kind !== "images") return;
  ev.preventDefault();
  if (result.value !== el.value) {
    const cursor = result.cursor;
    setInput(result.value);
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(cursor, cursor);
    });
  }
  addPastedImages(result.files);
}

export function PendingImageChips({
  items: chips,
  onRemove,
}: {
  items: readonly PendingImage[];
  onRemove: (id: string) => void;
}) {
  if (chips.length === 0) return null;
  return (
    <div className="sy-rail-paste-row" aria-label="Images attached to the next message">
      {chips.map((item) => (
        <div
          key={item.id}
          className={
            "sy-rail-paste-chip"
            + (item.status === "error" ? " sy-rail-paste-chip--err" : "")
          }
          title={item.status === "error" ? (item.error ?? "upload failed") : item.name}
        >
          <img src={item.previewUrl} alt={item.name} className="sy-rail-paste-thumb" />
          {item.status === "uploading" && (
            <span className="sy-rail-paste-status">uploading</span>
          )}
          {item.status === "error" && (
            <span className="sy-rail-paste-status">{item.error ?? "upload failed"}</span>
          )}
          <button
            type="button"
            className="sy-rail-paste-rm"
            aria-label={`Remove ${item.name}`}
            onClick={() => onRemove(item.id)}
          >
            ×
          </button>
        </div>
      ))}
    </div>
  );
}
