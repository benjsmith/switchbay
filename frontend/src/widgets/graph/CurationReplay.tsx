import { useEffect, useRef } from "react";
import { playCurationReplay, type HistoryDoc } from "./curationReplayAnim";

/**
 * CurationReplay — opening animation for the Graph tab.
 *
 * Plays back the workspace's wiki/ git history as a force-directed
 * graph that grows and progressively comes to resemble the real
 * graph viewer. Animation lives in curationReplayAnim.ts (shared
 * with the VS Code Graph webview).
 */

type Props = {
  replayKey?: number;
  onDone?: () => void;
  fading?: boolean;
};

export default function CurationReplay({ replayKey = 0, onDone, fading }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const onDoneRef = useRef(onDone);
  onDoneRef.current = onDone;
  const nodeCountSpanRef = useRef<HTMLSpanElement>(null);
  const edgeCountSpanRef = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    let cancelled = false;
    let stop = () => { /* set below */ };
    if (nodeCountSpanRef.current) nodeCountSpanRef.current.textContent = "0";
    if (edgeCountSpanRef.current) edgeCountSpanRef.current.textContent = "0";

    (async () => {
      let history: HistoryDoc | null = null;
      try {
        const r = await fetch("/api/curation/history");
        if (r.ok) history = (await r.json()) as HistoryDoc;
      } catch {
        // Quiet: empty canvas is better than crashing the overlay.
      }
      if (cancelled || !svgRef.current) return;
      stop = playCurationReplay(svgRef.current, {
        history,
        onDone: () => onDoneRef.current?.(),
        onCounts: (n, e) => {
          if (nodeCountSpanRef.current) nodeCountSpanRef.current.textContent = String(n);
          if (edgeCountSpanRef.current) edgeCountSpanRef.current.textContent = String(e);
        },
      });
    })();

    return () => {
      cancelled = true;
      stop();
    };
  }, [replayKey]);

  return (
    <div
      className={
        "sy-curation-replay" + (fading ? " sy-curation-replay--fading" : "")
      }
    >
      <svg ref={svgRef} className="sy-curation-replay-svg" />
      <div className="sy-curation-replay-label">
        Replaying curation history — scroll or drag to zoom/pan
      </div>
      <div className="sy-graph-count">
        <span ref={nodeCountSpanRef}>0</span> nodes ·{" "}
        <span ref={edgeCountSpanRef}>0</span> edges
      </div>
    </div>
  );
}
