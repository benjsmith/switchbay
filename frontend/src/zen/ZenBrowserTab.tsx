import { useState } from "react";
import type { GraphData } from "../widgets/graph/types";
import FileBrowser from "../sidebar/FileBrowser";
import SourceBrowser from "../sidebar/SourceBrowser";
import WikiPane from "../sidebar/WikiPane";
import { useIngestDrop } from "../sidebar/ingestDrop";

/**
 * Zen Browser surface: the same three browsers the Power sidebar
 * carries — on-disk files, the wiki page list, and source provenance
 * — but side by side as equal columns rather than stacked behind a
 * Files|Sources toggle. The Zen right pane is a whole pane wide, so
 * there's no reason to make the user flip between two of them.
 *
 * Same parts, same ingest pipeline: the whole surface is one drop
 * target (D5), identical to the Power column.
 */

type Props = {
  data: GraphData | null;
  error: string | null;
  /** Counter bumped by App on `files_changed` WS broadcasts. */
  filesVersion: number;
};

export default function ZenBrowserTab({ data, error, filesVersion }: Props) {
  const [refreshKey, setRefreshKey] = useState(0);
  const { uploading, dragOver, dropProps, ingestOne } = useIngestDrop();
  const key = refreshKey + filesVersion;

  return (
    <div className="sy-zen-browse" {...dropProps}>
      <div className="sy-zen-browse-col">
        <FileBrowser refreshKey={key} />
      </div>
      <div className="sy-zen-browse-col sy-zen-browse-col--wiki">
        <div className="sy-fb-head">
          <span>WIKI</span>
          {uploading && (
            <span
              className="sy-side-uploading"
              title="Ingest agent running — the Agents surface has the transcript"
            >
              ⟳ {uploading}
            </span>
          )}
        </div>
        {error ? (
          <div className="sy-side-body" style={{ color: "var(--type-fact)" }}>
            {error}
          </div>
        ) : (
          <div className="sy-zen-browse-pages">
            <WikiPane
              data={data}
              onGraphBuild={() => setRefreshKey((k) => k + 1)}
              onUploadFile={ingestOne}
            />
          </div>
        )}
      </div>
      <div className="sy-zen-browse-col">
        <SourceBrowser refreshKey={key} />
      </div>
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
