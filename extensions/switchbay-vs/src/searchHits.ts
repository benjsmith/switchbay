/** Graph-search path matching shared by the Wiki tree, Files tree, and
 *  Explorer decorations. Paths arrive as wiki-relative (`entities/x.md`)
 *  or already rooted (`wiki/…`, `vault/…`). */

export function normalizeRel(p: string): string {
  return p.replace(/^\.\//, "").replace(/^\/+/, "").replace(/\\/g, "/");
}

export function withWikiPrefix(rel: string): string {
  const n = normalizeRel(rel);
  if (
    n.startsWith("wiki/")
    || n.startsWith("vault/")
    || n.startsWith("slideshows/")
    || n.startsWith("reports/")
    || n.startsWith("sketches/")
  ) {
    return n;
  }
  return n ? `wiki/${n}` : n;
}

export function relIsHit(rel: string, hits: Iterable<string>): boolean {
  const set = hits instanceof Set ? hits : new Set([...hits].map(normalizeRel));
  if (set.size === 0) return false;
  const n = normalizeRel(rel);
  if (!n) return false;
  const withWiki = withWikiPrefix(n);
  const without = withWiki.startsWith("wiki/") ? withWiki.slice("wiki/".length) : n;
  return set.has(n) || set.has(withWiki) || set.has(without);
}

/** True if `dirRel` is an ancestor of (or equal to) a hit. Used to
 *  auto-expand folders so a graph-search match is visible. */
export function dirContainsHit(dirRel: string, hits: Iterable<string>): boolean {
  const dir = normalizeRel(dirRel);
  for (const raw of hits) {
    const hit = withWikiPrefix(raw);
    if (!dir) return Boolean(hit);
    if (hit === dir || hit.startsWith(`${dir}/`)) return true;
    const without = hit.startsWith("wiki/") ? hit.slice("wiki/".length) : hit;
    if (without === dir || without.startsWith(`${dir}/`)) return true;
  }
  return false;
}

export function displayNameForWikiRoot(wikiRoot: string | undefined): string | undefined {
  if (!wikiRoot) return undefined;
  const trimmed = wikiRoot.replace(/[\\/]+$/, "");
  const base = trimmed.split(/[/\\]/).pop();
  return base || undefined;
}
