import { useCallback, useRef, useState } from "react";
import { ingestFile } from "../lib/ingest";

/**
 * Drop-to-ingest, shared by every browse surface (D5). The Power
 * sidebar column and the Zen Browser surface are the same pipeline as
 * the `+` upload: dropped files or folders are staged into the vault
 * and each dispatches a background ingest agent.
 *
 * Lives apart from Sidebar.tsx so the two surfaces can't drift — a
 * second copy of the traversal/confirm/concurrency rules is exactly
 * the kind of thing that rots on one side only.
 */

/** How many dropped files trigger a "really dispatch N agents?"
 *  confirm — each file becomes one background ingest run. */
export const DROP_CONFIRM_AT = 10;
/** Hard cap per drop. The bulk-ingest architecture step (charter,
 *  Phase 8 stage 4) is the designed path for whole-corpus imports —
 *  a Browser drop is for a folder of documents, not ~/Documents. */
export const DROP_MAX_FILES = 100;

/** Recursively collect File objects from a drop's DataTransferItemList
 *  (webkitGetAsEntry API — the only way dropped DIRECTORIES yield
 *  their contents). Hidden entries are skipped; traversal stops at
 *  DROP_MAX_FILES. */
export async function collectDroppedFiles(items: DataTransferItemList): Promise<File[]> {
  const out: File[] = [];
  const readEntries = (r: FileSystemDirectoryReader) =>
    new Promise<FileSystemEntry[]>((res) => r.readEntries(res, () => res([])));
  const fileOf = (e: FileSystemFileEntry) =>
    new Promise<File | null>((res) => e.file(res, () => res(null)));
  const walk = async (entry: FileSystemEntry): Promise<void> => {
    if (out.length >= DROP_MAX_FILES) return;
    if (entry.name.startsWith(".")) return;
    if (entry.isFile) {
      const f = await fileOf(entry as FileSystemFileEntry);
      if (f) out.push(f);
      return;
    }
    if (entry.isDirectory) {
      const reader = (entry as FileSystemDirectoryEntry).createReader();
      // readEntries returns batches (~100); keep draining until empty.
      for (;;) {
        const batch = await readEntries(reader);
        if (batch.length === 0) break;
        for (const child of batch) await walk(child);
        if (out.length >= DROP_MAX_FILES) break;
      }
    }
  };
  const entries: FileSystemEntry[] = [];
  for (const item of Array.from(items)) {
    if (item.kind !== "file") continue;
    const entry = item.webkitGetAsEntry?.();
    if (entry) entries.push(entry);
  }
  for (const e of entries) await walk(e);
  return out;
}

export type IngestDrop = {
  /** Progress label while runs are being dispatched (`"3/12"` for a
   *  drop, the filename for a single `+` pick). null when idle. */
  uploading: string | null;
  /** True while a file drag hovers the surface — render the veil. */
  dragOver: boolean;
  /** Spread onto the element that should accept drops. */
  dropProps: {
    onDragEnter: (ev: React.DragEvent) => void;
    onDragLeave: () => void;
    onDragOver: (ev: React.DragEvent) => void;
    onDrop: (ev: React.DragEvent) => void;
  };
  /** The `+` upload path: one file, straight to a run. */
  ingestOne: (file: File) => Promise<void>;
};

export function useIngestDrop(): IngestDrop {
  const [uploading, setUploading] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  // Suppresses the flicker of dragleave firing on every child hop.
  const dragDepth = useRef(0);

  const ingestOne = useCallback(async (file: File) => {
    setUploading(file.name);
    try {
      const runId = await ingestFile(file);
      if (!runId) {
        window.alert("Upload failed");
        return;
      }
      // Drop the user into Agent Dashboard with the run's transcript
      // auto-expanded. The existing rail-jump bridge does the tab swap
      // (or Zen surface swap) + expand-after-mount choreography.
      window.dispatchEvent(new CustomEvent("sy:open-agents-run", {
        detail: { run_id: runId },
      }));
    } catch (e) {
      window.alert(`Upload failed: ${(e as Error).message}`);
    } finally {
      setUploading(null);
    }
  }, []);

  const onDrop = useCallback(async (ev: React.DragEvent) => {
    ev.preventDefault();
    dragDepth.current = 0;
    setDragOver(false);
    let files: File[];
    try {
      files = await collectDroppedFiles(ev.dataTransfer.items);
    } catch {
      files = Array.from(ev.dataTransfer.files ?? []);
    }
    if (files.length === 0) return;
    if (files.length >= DROP_CONFIRM_AT) {
      const capped = files.length >= DROP_MAX_FILES
        ? ` (capped at ${DROP_MAX_FILES} — for a whole corpus, ask the rail to plan a bulk ingest instead)`
        : "";
      const go = window.confirm(
        `Ingest ${files.length} files${capped}? Each dispatches a background ingest agent.`,
      );
      if (!go) return;
    }
    let done = 0;
    let failed = 0;
    let firstRun: string | null = null;
    setUploading(`0/${files.length}`);
    // Small concurrency: 3 in flight keeps the daemon + provider sane
    // while a folder of PDFs streams in.
    const queue = [...files];
    const worker = async () => {
      for (;;) {
        const f = queue.shift();
        if (!f) return;
        try {
          const rid = await ingestFile(f);
          if (rid) firstRun = firstRun ?? rid;
          else failed += 1;
        } catch {
          failed += 1;
        }
        done += 1;
        setUploading(`${done}/${files.length}`);
      }
    };
    await Promise.all(Array.from({ length: Math.min(3, files.length) }, worker));
    setUploading(null);
    if (failed > 0) {
      window.alert(`${failed} of ${files.length} uploads failed — see the daemon log.`);
    }
    if (firstRun) {
      window.dispatchEvent(new CustomEvent("sy:open-agents-run", {
        detail: { run_id: firstRun },
      }));
    }
  }, []);

  return {
    uploading,
    dragOver,
    ingestOne,
    dropProps: {
      onDragEnter: (ev) => {
        if (!ev.dataTransfer.types.includes("Files")) return;
        dragDepth.current += 1;
        setDragOver(true);
      },
      onDragLeave: () => {
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setDragOver(false);
      },
      onDragOver: (ev) => {
        if (!ev.dataTransfer.types.includes("Files")) return;
        ev.preventDefault();
      },
      onDrop: (ev) => void onDrop(ev),
    },
  };
}
