/** JSON-safe cell / payload values. DuckDB-WASM (and Arrow) often
 *  hand back `bigint` / objects whose `valueOf()` is a bigint —
 *  `JSON.stringify` then throws and used to crash the Table tab. */

export function jsonSafe(v: unknown): unknown {
  if (v === null || v === undefined) return v;
  const t = typeof v;
  if (t === "string" || t === "boolean") return v;
  if (t === "number") return Number.isFinite(v as number) ? v : String(v);
  if (t === "bigint") {
    const n = Number(v);
    return Number.isSafeInteger(n) ? n : (v as bigint).toString();
  }
  if (v instanceof Date) return v.toISOString();
  if (Array.isArray(v)) return v.map(jsonSafe);
  if (t === "object") {
    const obj = v as { toArray?: () => unknown; valueOf?: () => unknown };
    if (typeof obj.toArray === "function") {
      try { return jsonSafe(obj.toArray()); } catch { /* fall through */ }
    }
    if (typeof obj.valueOf === "function") {
      try {
        const inner = obj.valueOf();
        if (inner !== v && (inner == null || typeof inner !== "object")) {
          return jsonSafe(inner);
        }
      } catch { /* fall through */ }
    }
    try {
      return JSON.parse(JSON.stringify(v, (_k, x) =>
        typeof x === "bigint" ? jsonSafe(x) : x));
    } catch {
      return String(v);
    }
  }
  return String(v);
}

export function jsonSafeStringify(value: unknown): string {
  return JSON.stringify(value, (_k, v) =>
    typeof v === "bigint" ? jsonSafe(v) : v);
}
