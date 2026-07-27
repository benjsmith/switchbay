import { useEffect, useRef, useState } from "react";
import { sidebarTemplate } from "../widgets/graph/template";
import type { GraphData } from "../widgets/graph/types";
import FileBrowser from "./FileBrowser";
import SourceBrowser from "./SourceBrowser";
import { ingestFile } from "../lib/ingest";
import ThemeToggle from "../layout/ThemeToggle";
import ModeToggle from "../layout/ModeToggle";

type Props = {
  data: GraphData | null;
  error: string | null;
  /** Counter bumped by App on `files_changed` WS broadcasts. Folded
   *  into FileBrowser's refreshKey so an agent's Write or fileops
   *  delete shows up without a manual refresh. */
  filesVersion: number;
};

/** How many dropped files trigger a "really dispatch N agents?"
 *  confirm — each file becomes one background ingest run. */
const DROP_CONFIRM_AT = 10;
/** Hard cap per drop. The bulk-ingest architecture step (charter,
 *  Phase 8 stage 4) is the designed path for whole-corpus imports —
 *  a Browser drop is for a folder of documents, not ~/Documents. */
const DROP_MAX_FILES = 100;

/** Recursively collect File objects from a drop's DataTransferItemList
 *  (webkitGetAsEntry API — the only way dropped DIRECTORIES yield
 *  their contents). Hidden entries are skipped; traversal stops at
 *  DROP_MAX_FILES. */
async function collectDroppedFiles(items: DataTransferItemList): Promise<File[]> {
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

/** The bottom pane's Files|Sources segmented toggle (D1). */
function BottomSeg({
  view, onChange,
}: {
  view: "files" | "sources";
  onChange: (v: "files" | "sources") => void;
}) {
  return (
    <div className="sy-side-seg" role="tablist" aria-label="Bottom pane view">
      <button
        type="button"
        role="tab"
        aria-selected={view === "files"}
        className={"sy-side-seg-btn" + (view === "files" ? " sy-side-seg-btn--on" : "")}
        onClick={() => onChange("files")}
        title="The workspace's on-disk file tree"
      >
        Files
      </button>
      <button
        type="button"
        role="tab"
        aria-selected={view === "sources"}
        className={"sy-side-seg-btn" + (view === "sources" ? " sy-side-seg-btn--on" : "")}
        onClick={() => onChange("sources")}
        title="Where this wiki's pages came from — external files and links the curator extracted"
      >
        Sources
      </button>
    </div>
  );
}

/**
 * Switch Bay Browser. Stacks two views vertically inside the left
 * column:
 *   - top: CE's forked sidebar (page list grouped by type, search,
 *     `+` upload) — the wiki stays always in view.
 *   - bottom: the lower-level browse surface — Files|Sources toggle
 *     (D1) between the on-disk file tree (OS-style ops) and the
 *     provenance tree over external `extracted_from` paths.
 * The whole column is a drop target (D5): dropping files or folders
 * stages them into the vault and dispatches background ingest agents
 * — same pipeline as the `+` upload.
 */
export default function Sidebar({ data, error, filesVersion }: Props) {
  const slotRef = useRef<HTMLDivElement>(null);
  const lastDataRef = useRef<GraphData | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [refreshKey, setRefreshKey] = useState(0);
  const [uploading, setUploading] = useState<string | null>(null);
  // Bottom-pane mode (D1): the wiki page list stays always-visible on
  // top; the BOTTOM pane is the lower-level browse surface and flips
  // between the on-disk file tree and the external-sources
  // provenance tree.
  const [view, setView] = useState<"files" | "sources">("files");
  const [dragOver, setDragOver] = useState(false);
  // Suppresses the flicker of dragleave firing on every child hop.
  const dragDepth = useRef(0);

  useEffect(() => {
    if (!slotRef.current) return;
    if (!slotRef.current.querySelector("#sidebar")) {
      slotRef.current.innerHTML = sidebarTemplate;
    }
    if (data && data !== lastDataRef.current) {
      lastDataRef.current = data;
      window.Sidebar.init(data);
      // A new build => the on-disk file set may have shifted too.
      setRefreshKey((k) => k + 1);
    } else if (!data) {
      // Workspace switched to one with no built graph (data === null).
      // window.Sidebar.init only renders for truthy data, so without
      // this the previous workspace's page list stays in #sidebar-list.
      // Clear it explicitly so the Browser empties on the switch.
      lastDataRef.current = null;
      const list = slotRef.current.querySelector("#sidebar-list");
      if (list) list.innerHTML = "";
      const search = slotRef.current.querySelector<HTMLInputElement>("#sidebar-search");
      if (search) search.value = "";
    }
  }, [data]);

  // Wire the CE-template `#sidebar-upload` button to a hidden file
  // input. Hooking up after the template lands; runs after every
  // re-mount (workspace switch re-injects the markup).
  useEffect(() => {
    const btn = slotRef.current?.querySelector<HTMLButtonElement>("#sidebar-upload");
    if (!btn) return;
    btn.setAttribute("data-tour", "add-files");
    const onClick = () => fileInputRef.current?.click();
    btn.addEventListener("click", onClick);
    return () => btn.removeEventListener("click", onClick);
  }, [data]);

  const onFileChosen = async (ev: React.ChangeEvent<HTMLInputElement>) => {
    const file = ev.target.files?.[0];
    ev.target.value = "";  // reset so re-picking the same file fires change
    if (!file) return;
    setUploading(file.name);
    try {
      const runId = await ingestFile(file);
      if (!runId) {
        window.alert("Upload failed");
        return;
      }
      // Drop the user into Agent Dashboard with the run's
      // transcript auto-expanded. The existing rail-jump bridge
      // does the tab swap + expand-after-mount choreography.
      window.dispatchEvent(new CustomEvent("sy:open-agents-run", {
        detail: { run_id: runId },
      }));
    } catch (e) {
      window.alert(`Upload failed: ${(e as Error).message}`);
    } finally {
      setUploading(null);
    }
  };

  const onDrop = async (ev: React.DragEvent) => {
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
  };

  return (
    // display:contents — the wrapper adds DnD without touching the
    // column's flex layout; events bubble up from the panes.
    <div
      style={{ display: "contents" }}
      onDragEnter={(ev) => {
        if (!ev.dataTransfer.types.includes("Files")) return;
        dragDepth.current += 1;
        setDragOver(true);
      }}
      onDragLeave={() => {
        dragDepth.current = Math.max(0, dragDepth.current - 1);
        if (dragDepth.current === 0) setDragOver(false);
      }}
      onDragOver={(ev) => {
        if (!ev.dataTransfer.types.includes("Files")) return;
        ev.preventDefault();
      }}
      onDrop={(ev) => void onDrop(ev)}
    >
      <div className="sy-side-head" data-tour="browser">
        <span>BROWSER</span>
        {uploading && (
          <span
            className="sy-side-uploading"
            title="Ingest agent running — click to open Agents"
          >
            ⟳ {uploading}
          </span>
        )}
      </div>
      <input
        ref={fileInputRef}
        type="file"
        style={{ display: "none" }}
        onChange={(e) => void onFileChosen(e)}
      />
      <div className="sy-side-pages">
        <div ref={slotRef} className="sy-side-pages-mount" />
      </div>
      {error && (
        <div className="sy-side-body" style={{ color: "var(--type-fact)" }}>
          {error}
        </div>
      )}
      <div className="sy-side-files">
        {view === "files" ? (
          <FileBrowser
            refreshKey={refreshKey + filesVersion}
            headExtra={
              <BottomSeg view={view} onChange={setView} />
            }
          />
        ) : (
          <SourceBrowser
            refreshKey={refreshKey + filesVersion}
            headExtra={
              <BottomSeg view={view} onChange={setView} />
            }
          />
        )}
      </div>
      <footer className="sy-side-bottom">
        <ThemeToggle />
        <ModeToggle />
      </footer>
      {dragOver && (
        <div className="sy-side-dropveil" aria-hidden="true">
          <div className="sy-side-dropveil-inner">
            Drop to ingest — files (or a folder) are staged into the
            vault and background agents extract wiki pages.
          </div>
        </div>
      )}
    </div>
  );
}
