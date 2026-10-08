import CeAtlasEmbed from "./CeAtlasEmbed";
import { useCeGraph } from "./useProxiedSkillEmbeds";

/**
 * The Graph surface for both Power (Graph tab) and Zen (left pane):
 * Curiosity Engine's own viewer through `/embed/ce`. Without a CE
 * install the shell hides the Graph tab; this placeholder only shows
 * where a surface is always present (Zen) or while settings load.
 */
export default function CeGraphSurface(
  { showAddFile, suppressDocModal }: { showAddFile?: boolean; suppressDocModal?: boolean },
) {
  const ce = useCeGraph();
  if (ce === null) {
    return <div className="sy-placeholder"><p>Loading…</p></div>;
  }
  if (!ce.installed) {
    return (
      <div className="sy-placeholder">
        <h2>Graph</h2>
        <p>
          The Graph comes from Curiosity Engine, which isn't installed.
          Files, search, Agents and the rest of Switch Bay work without it.
        </p>
      </div>
    );
  }
  if (!ce.hasWiki) {
    return (
      <div className="sy-placeholder">
        <h2>Graph</h2>
        <p>This workspace has no <code>wiki/</code> yet, so there's no graph to show.</p>
      </div>
    );
  }
  return <CeAtlasEmbed showAddFile={showAddFile} suppressDocModal={suppressDocModal} />;
}
