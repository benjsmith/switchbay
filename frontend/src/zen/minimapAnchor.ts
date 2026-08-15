/**
 * Where the Classic/Atlas overview map sits in Zen.
 *
 * The map is `position:absolute` inside `#graph` (the left pane). The
 * floating chat box / collapsed pill is a sibling of that pane, so
 * they share no stacking context — overlap must be avoided by lifting
 * the map, not by z-index. Docked chat lives in the right pane and
 * never intersects the map's default corner.
 */

export type Rect = {
  left: number;
  right: number;
  top: number;
  bottom: number;
  width: number;
  height: number;
};

const INSET = 12;
const MAP = { wide: { w: 190, h: 128 }, compact: { w: 126, h: 88 } };

export function minimapSize(graph: Pick<Rect, "width" | "height">): { w: number; h: number } {
  return Math.min(graph.width, graph.height) <= 520 ? MAP.compact : MAP.wide;
}

/** CSS `bottom` (px) that keeps the map off the floating overlay. */
export function minimapBottomOffset(graph: Rect, overlay: Rect | null, inset = INSET): number {
  if (!overlay) return inset;
  const { w, h } = minimapSize(graph);
  const mapLeft = graph.right - inset - w;
  const mapTop = graph.bottom - inset - h;
  const mapRight = graph.right - inset;
  const mapBottom = graph.bottom - inset;
  const overlaps =
    overlay.left < mapRight &&
    overlay.right > mapLeft &&
    overlay.top < mapBottom &&
    overlay.bottom > mapTop;
  if (!overlaps) return inset;
  return Math.max(inset, Math.round(graph.bottom - overlay.top + inset));
}
