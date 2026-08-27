/**
 * Desk window length. Accepts hours as a number (including fractions)
 * or strings like "15 min", "15 mins", "2h", "0.25".
 * Returns hours, or null if unset/invalid.
 */
export function parseDuration(raw: unknown): number | null {
  if (raw == null || raw === "") return null;
  if (typeof raw === "number") {
    return Number.isFinite(raw) && raw > 0 ? raw : null;
  }
  const text = String(raw).trim().toLowerCase().replace(/,/g, "");
  if (!text) return null;
  const m = text.match(/^([\d.]+)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)?$/i);
  if (!m) return null;
  const n = Number(m[1]);
  if (!Number.isFinite(n) || n < 0) return null;
  const unit = (m[2] || "h").toLowerCase();
  if (unit.startsWith("m")) return n / 60;
  return n;
}

export function formatDuration(hours: number | null | undefined): string {
  if (hours == null || !Number.isFinite(hours) || hours <= 0) return "";
  const minsTotal = Math.round(hours * 60);
  if (minsTotal < 60) return `${minsTotal} min`;
  const h = Math.floor(minsTotal / 60);
  const m = minsTotal % 60;
  if (m === 0) return `${h}h`;
  return `${h}h ${m} min`;
}
