/**
 * Client-side filter for the Plot tab. The index is the text already
 * loaded with the gallery (title, caption, axis titles, series legend).
 * Typing does not ask the server again.
 */

export type SearchFields = {
  title?: string;
  name?: string;
  caption?: string;
  summary?: string;
  axisTitles?: string[];
  axis_titles?: string[];
  legendTitles?: string[];
  legend_titles?: string[];
  legendEntries?: string[];
  legend_entries?: string[];
};

export type TextPart = { text: string; hit: boolean };

function asList(value: string[] | undefined): string[] {
  return Array.isArray(value) ? value : [];
}

export function searchBlob(item: SearchFields): string {
  const bits = [
    item.title,
    item.name,
    item.caption,
    item.summary,
    ...asList(item.axisTitles),
    ...asList(item.axis_titles),
    ...asList(item.legendTitles),
    ...asList(item.legend_titles),
    ...asList(item.legendEntries),
    ...asList(item.legend_entries),
  ];
  return bits
    .filter((part) => typeof part === "string" && part.trim())
    .join("\n")
    .toLowerCase();
}

export function queryTokens(query: string): string[] {
  return query.trim().toLowerCase().split(/\s+/).filter(Boolean);
}

export function matchesQuery(blob: string, query: string): boolean {
  const tokens = queryTokens(query);
  if (tokens.length === 0) return true;
  return tokens.every((token) => blob.includes(token));
}

export function highlightParts(text: string, query: string): TextPart[] {
  if (!text) return [{ text: "", hit: false }];
  const tokens = [...new Set(queryTokens(query))];
  if (tokens.length === 0) return [{ text, hit: false }];
  const lower = text.toLowerCase();
  const ranges: Array<[number, number]> = [];
  for (const token of tokens) {
    let from = 0;
    while (from <= lower.length - token.length) {
      const at = lower.indexOf(token, from);
      if (at < 0) break;
      ranges.push([at, at + token.length]);
      from = at + token.length;
    }
  }
  if (ranges.length === 0) return [{ text, hit: false }];
  ranges.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const merged: Array<[number, number]> = [];
  for (const range of ranges) {
    const last = merged[merged.length - 1];
    if (!last || range[0] > last[1]) merged.push([range[0], range[1]]);
    else last[1] = Math.max(last[1], range[1]);
  }
  const parts: TextPart[] = [];
  let cursor = 0;
  for (const [start, end] of merged) {
    if (start > cursor) parts.push({ text: text.slice(cursor, start), hit: false });
    parts.push({ text: text.slice(start, end), hit: true });
    cursor = end;
  }
  if (cursor < text.length) parts.push({ text: text.slice(cursor), hit: false });
  return parts;
}
