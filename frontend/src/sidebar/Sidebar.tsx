import { useEffect, useState } from "react";
import type { GraphData } from "../widgets/graph/types";
import FileBrowser from "./FileBrowser";
import SourceBrowser from "./SourceBrowser";
import WikiPane from "./WikiPane";
import { useIngestDrop } from "./ingestDrop";
import ThemeToggle from "../layout/ThemeToggle";
import ModeToggle from "../layout/ModeToggle";
import CeSidebarSlot from "../widgets/embed/CeSidebarSlot";
import { useProxiedSkillEmbeds } from "../widgets/embed/useProxiedSkillEmbeds";
import { resetCeEmbedSession } from "../widgets/embed/ceEmbedSession";

type Props = {
  data: GraphData | null;
  error: string | null;
  /** Counter bumped by App on `files_changed` WS broadcasts. Folded
   *  into FileBrowser's refreshKey so an agent's Write or fileops
   *  delete shows up without a manual refresh. */
  filesVersion: number;
};

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
 * Switch Bay Browser (Power mode). Stacks two views vertically inside
 * the left column:
 *   - top: CE's forked sidebar (page list grouped by type, search,
 *     `+` upload) — the wiki stays always in view.
 *   - bottom: the lower-level browse surface — Files|Sources toggle
 *     (D1) between the on-disk file tree (OS-style ops) and the
 *     provenance tree over external `extracted_from` paths.
 * The whole column is a drop target (D5): dropping files or folders
 * stages them into the vault and dispatches background ingest agents
 * — the `+` button instead opens the upload dialog (vault/raw/,
 * ingest optional).
 *
 * Zen mode shows the same three browsers side by side instead — see
 * ZenBrowserTab, which composes the same parts.
 */
export default function Sidebar({ data, error, filesVersion }: Props) {
  const proxied = useProxiedSkillEmbeds();
  const [refreshKey, setRefreshKey] = useState(0);
  // Bottom-pane mode (D1): the wiki page list stays always-visible on
  // top; the BOTTOM pane is the lower-level browse surface and flips
  // between the on-disk file tree and the external-sources
  // provenance tree.
  const [view, setView] = useState<"files" | "sources">("files");
  const { uploading, dragOver, dropProps } = useIngestDrop();
  useEffect(() => {
    const onReveal = () => setView("files");
    window.addEventListener("sy:reveal-file", onReveal);
    return () => window.removeEventListener("sy:reveal-file", onReveal);
  }, []);

  // Workspace-keyed remount of <Sidebar> tears the CE dual-mount session
  // so the next workspace does not keep the previous wiki's Pages list.
  useEffect(() => {
    return () => {
      resetCeEmbedSession();
    };
  }, []);

  return (
    // display:contents — the wrapper adds DnD without touching the
    // column's flex layout; events bubble up from the panes.
    <div style={{ display: "contents" }} {...dropProps}>
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
      {proxied === null ? (
        <div className="sy-side-pages">
          <p className="sy-ce-sidebar-slot-status">Loading browser…</p>
        </div>
      ) : proxied === true ? (
        // One CE page list (Pages|Files) in the shell — persists across
        // Graph/Agents/Editor. Graph pane is canvas-only via CeAtlasEmbed.
        <div className="sy-side-pages sy-side-pages--ce-embed">
          <CeSidebarSlot />
        </div>
      ) : (
        <>
          <div className="sy-side-pages">
            <WikiPane
              data={data}
              onGraphBuild={() => setRefreshKey((k) => k + 1)}
            />
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
        </>
      )}
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
