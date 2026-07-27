/** A1 notation helpers for the Sheet tab (Univer is 0-based). */

const CELL_RE = /^\$?([A-Za-z]+)\$?(\d+)$/;
const RANGE_RE = /^\$?([A-Za-z]+)\$?(\d+)(?::\$?([A-Za-z]+)\$?(\d+))?$/;

export function colToLetter(col: number): string {
  if (col < 0) throw new Error(`column must be >= 0, got ${col}`);
  let n = col + 1;
  let out = "";
  while (n > 0) {
    const rem = (n - 1) % 26;
    out = String.fromCharCode(65 + rem) + out;
    n = Math.floor((n - 1) / 26);
  }
  return out;
}

export function letterToCol(letters: string): number {
  let n = 0;
  for (const ch of letters.toUpperCase()) {
    if (ch < "A" || ch > "Z") throw new Error(`invalid column: ${letters}`);
    n = n * 26 + (ch.charCodeAt(0) - 64);
  }
  return n - 1;
}

export function cellToA1(row: number, col: number): string {
  return `${colToLetter(col)}${row + 1}`;
}

/** Parse `H18` → {row, col} 0-based. */
export function parseA1Cell(a1: string): { row: number; col: number } {
  const m = CELL_RE.exec(a1.trim());
  if (!m) throw new Error(`invalid A1 cell: ${a1}`);
  const col = letterToCol(m[1]);
  const row = parseInt(m[2], 10) - 1;
  if (row < 0) throw new Error(`invalid A1 cell: ${a1}`);
  return { row, col };
}

/** Parse `H18` or `C2:H17` → {row, col, rowCount, colCount}. */
export function parseA1Range(spec: string): {
  row: number;
  col: number;
  rowCount: number;
  colCount: number;
} {
  const m = RANGE_RE.exec(spec.trim());
  if (!m) throw new Error(`invalid A1 range: ${spec}`);
  const c1 = letterToCol(m[1]);
  const r1 = parseInt(m[2], 10) - 1;
  if (m[3] == null) {
    return { row: r1, col: c1, rowCount: 1, colCount: 1 };
  }
  const c2 = letterToCol(m[3]);
  const r2 = parseInt(m[4], 10) - 1;
  if (r1 < 0 || r2 < 0) throw new Error(`invalid A1 range: ${spec}`);
  const row = Math.min(r1, r2);
  const col = Math.min(c1, c2);
  return {
    row,
    col,
    rowCount: Math.abs(r2 - r1) + 1,
    colCount: Math.abs(c2 - c1) + 1,
  };
}

export function rangeToA1(
  row: number,
  col: number,
  rowCount: number,
  colCount: number,
): string {
  const a = cellToA1(row, col);
  if (rowCount <= 1 && colCount <= 1) return a;
  return `${a}:${cellToA1(row + rowCount - 1, col + colCount - 1)}`;
}
