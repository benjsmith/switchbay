import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useSelection } from "../selection/SelectionContext";
import { useTabs } from "../center/TabsContext";
import { notifyHtmlDeckOpen } from "../widgets/htmldeck/htmlDeckOpen";

type FileNode = {
  name: string;
  path: string;
  isDir: boolean;
  children: FileNode[];
};

type CtxMenu = { x: number; y: number; path: string; isDir: boolean };

/** A pack-declared file-extension handler. The shape mirrors
 *  packstore.py's Manifest.file_routes plus the pack/scope
 *  annotations /api/file-routes appends. */
type FileRoute = {
  ext: string;
  action: string;
  label?: string;
  description?: string;
  endpoint?: string;
  tab_kind?: string;
  selection_kind?: string;
  requires_binary?: string;
  primary?: boolean;
  pack?: string;
  scope?: string;
};

type SortMode = "asc" | "desc";

function buildTree(paths: string[], sort: SortMode): FileNode[] {
  const root: FileNode = { name: "", path: "", isDir: true, children: [] };
  for (const p of paths) {
    const parts = p.split("/");
    let node = root;
    for (let i = 0; i < parts.length; i++) {
      const isLeaf = i === parts.length - 1;
      const childName = parts[i];
      const childPath = parts.slice(0, i + 1).join("/");
      let child = node.children.find((c) => c.name === childName);
      if (!child) {
        child = { name: childName, path: childPath, isDir: !isLeaf, children: [] };
        node.children.push(child);
      }
      node = child;
    }
  }
  // Dirs first, then alpha (asc) or alpha-reversed (desc) within each kind.
  function sortRec(n: FileNode) {
    n.children.sort((a, b) => {
      if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
      const cmp = a.name.localeCompare(b.name);
      return sort === "asc" ? cmp : -cmp;
    });
    n.children.forEach(sortRec);
  }
  sortRec(root);
  return root.children;
}

function fileExt(path: string): string {
  const slash = path.lastIndexOf("/");
  const dot = path.lastIndexOf(".");
  if (dot <= slash) return "";
  return path.slice(dot + 1).toLowerCase();
}

/** Build a query matcher. Returns null on bad regex. Empty query matches all. */
function buildMatcher(query: string): ((path: string) => boolean) | null {
  const q = query.trim();
  if (!q) return () => true;
  // /pattern/flags
  const re = q.match(/^\/(.+)\/([gimsuy]*)$/);
  if (re) {
    try {
      const r = new RegExp(re[1], re[2] || "i");
      return (p) => r.test(p);
    } catch {
      return null;   // signal a bad regex so the UI can show feedback
    }
  }
  // *.ext glob → filetype-only match (case-insensitive)
  const glob = q.match(/^\*\.([A-Za-z0-9_]+)$/);
  if (glob) {
    const ext = glob[1].toLowerCase();
    return (p) => fileExt(p) === ext;
  }
  // Plain substring (case-insensitive against the full relative path).
  const lower = q.toLowerCase();
  return (p) => p.toLowerCase().includes(lower);
}

/** CSS-attribute escaping for `[data-fb-path="…"]` lookups.
 *  Workspace paths can contain quotes and backslashes; only those
 *  two break the attribute-equality selector form. */
function cssEscapeAttr(value: string): string {
  return value.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}


/** Extensions / special names the file browser routes to an
 *  internal Switch Bay tab on click. Kept here so the context
 *  menu's "Open in Switch Bay" item can disable itself + suggest
 *  the OS-default "Open" path when no internal viewer exists. */
const SWITCHBAY_TEXT_EXTS = [
  ".md",
  ".py", ".pyw",
  ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
  ".html", ".htm", ".css",
  ".json", ".jsonl", ".geojson",
  ".rs", ".go", ".swift", ".rb", ".rake",
  ".sh", ".bash", ".zsh", ".fish",
  ".toml", ".yaml", ".yml", ".ini", ".env",
  ".txt", ".log", ".csv", ".tsv",
  ".sql",
];
const SWITCHBAY_SPECIAL_NAMES = [
  "gemfile", "rakefile", "makefile", "dockerfile",
];
const SWITCHBAY_RENDERED_EXTS = [
  ".pptx",  // → image-deck in Sketch tab
  ".docx",  // → docx-import → Editor
];

/** Sealed library packages: slideshows|decks|reports|worksheets / <slug>. */
const PACKAGE_ROOTS = new Set([
  "slideshows", "decks", "reports", "worksheets",
]);

function isLibraryPackage(path: string): boolean {
  const parts = path.replace(/\/+$/, "").split("/");
  if (parts.length !== 2) return false;
  if (!PACKAGE_ROOTS.has(parts[0])) return false;
  return /^[a-zA-Z0-9][a-zA-Z0-9._-]{0,80}$/.test(parts[1]);
}

function packageSlugFromPath(path: string): string | null {
  const parts = path.replace(/\/+$/, "").split("/");
  if (parts.length >= 2 && PACKAGE_ROOTS.has(parts[0])) {
    if (parts.length === 2) {
      if (parts[1].includes(".")) {
        return parts[1].replace(/\.(html?|htm|pdf|json)$/i, "");
      }
      return parts[1] || null;
    }
    return parts[1] || null;
  }
  return null;
}

function slideshowSlugFromPath(path: string): string | null {
  const root = path.replace(/\/+$/, "").split("/")[0];
  if (root !== "slideshows" && root !== "decks") return null;
  return packageSlugFromPath(path);
}

function isSlideshowEntryHtml(path: string): boolean {
  const lower = path.toLowerCase();
  if (!lower.endsWith(".html") && !lower.endsWith(".htm")) return false;
  const parts = path.replace(/\/+$/, "").split("/");
  if (parts.length < 2) return false;
  if (parts[0] !== "slideshows" && parts[0] !== "decks") return false;
  if (parts.length === 2) return true;
  if (parts.length === 3 && /^index\.html?$/i.test(parts[2])) return true;
  return false;
}

function isReportEntry(path: string): boolean {
  const parts = path.replace(/\/+$/, "").split("/");
  if (parts[0] !== "reports" || parts.length < 2) return false;
  if (parts.length === 2 && isLibraryPackage(path)) return true;
  if (parts.length === 3) {
    const n = parts[2].toLowerCase();
    return n === "index.html" || n === "index.htm" || n === "report.pdf"
      || n.endsWith(".html") || n.endsWith(".pdf");
  }
  return false;
}

/** Nested file inside any sealed library package (not the package root). */
function isInsideLibraryPackage(path: string): boolean {
  const parts = path.replace(/\/+$/, "").split("/");
  if (parts.length < 3) return false;
  if (!PACKAGE_ROOTS.has(parts[0])) return false;
  return isLibraryPackage(`${parts[0]}/${parts[1]}`);
}

function isWorkspaceTextFile(path: string): boolean {
  const lower = path.toLowerCase();
  if (SWITCHBAY_TEXT_EXTS.some((ext) => lower.endsWith(ext))) return true;
  const base = lower.split("/").pop() ?? "";
  return SWITCHBAY_SPECIAL_NAMES.includes(base);
}

function canOpenInSwitchbay(path: string, isDir = false): boolean {
  if (isDir) return isLibraryPackage(path);
  if (isInsideLibraryPackage(path)) {
    if (isSlideshowEntryHtml(path) || isReportEntry(path)) return true;
    // workbook.json is not "open in Switch Bay" as sheet — package root is
    return false;
  }
  if (isSlideshowEntryHtml(path) || isReportEntry(path)) return true;
  const lower = path.toLowerCase();
  if (SWITCHBAY_TEXT_EXTS.some((ext) => lower.endsWith(ext))) return true;
  if (SWITCHBAY_RENDERED_EXTS.some((ext) => lower.endsWith(ext))) return true;
  const base = lower.split("/").pop() ?? "";
  if (SWITCHBAY_SPECIAL_NAMES.includes(base)) return true;
  return false;
}


/** Collect every directory path along a matched file's chain, so we can
 *  auto-expand the tree to reveal matches when a search/filter is active. */
function ancestorDirs(filePath: string): string[] {
  const parts = filePath.split("/");
  const out: string[] = [""];   // tree root
  let acc = "";
  for (let i = 0; i < parts.length - 1; i++) {
    acc = acc ? `${acc}/${parts[i]}` : parts[i];
    out.push(acc);
  }
  return out;
}

export default function FileBrowser({
  refreshKey,
  headExtra,
}: {
  refreshKey: number;
  /** Rendered in place of the FILES label — the Sidebar passes the
   *  Files|Sources segmented toggle (D1: the bottom pane is the
   *  lower-level browse surface; wiki stays always-visible above). */
  headExtra?: React.ReactNode;
}) {
  const [files, setFiles] = useState<string[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set([""]));
  /** Slideshow package dirs the user has opted to inspect (show media /
   *  deck.json / etc.). Sealed by default so the tree stays clean. */
  const [inspectedPackages, setInspectedPackages] = useState<Set<string>>(
    () => new Set(),
  );
  // Bumped whenever selection changes to a page path — drives the
  // scroll-into-view + transient highlight effect below.
  const [revealTick, setRevealTick] = useState(0);
  const [menu, setMenu] = useState<CtxMenu | null>(null);
  // Clamped on-screen position; set in the layout effect below
  // once we can measure the rendered menu's box.
  const [menuPos, setMenuPos] = useState<{ x: number; y: number } | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [confirmDel, setConfirmDel] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortMode>("asc");
  const [extFilter, setExtFilter] = useState<Set<string>>(() => new Set());
  const [filterOpen, setFilterOpen] = useState(false);
  // Pack-declared file-type actions. Keyed by extension (lower-
  // case, leading dot) so the right-click menu can list every
  // pack-provided handler for the current file.
  const [fileRoutes, setFileRoutes] = useState<Map<string, FileRoute[]>>(
    () => new Map(),
  );
  useEffect(() => {
    let cancelled = false;
    fetch("/api/file-routes")
      .then((r) => (r.ok ? r.json() : null))
      .then((b) => {
        if (cancelled || !b) return;
        const next = new Map<string, FileRoute[]>();
        for (const route of (b.routes as FileRoute[]) ?? []) {
          const ext = String(route.ext || "").toLowerCase();
          if (!ext) continue;
          const arr = next.get(ext) ?? [];
          arr.push(route);
          next.set(ext, arr);
        }
        setFileRoutes(next);
      })
      .catch(() => { /* packs unavailable — menu just has defaults */ });
    return () => { cancelled = true; };
  }, []);
  const { selection, setSelection } = useSelection();
  const { switchToKind } = useTabs();

  useEffect(() => {
    let cancelled = false;
    setError(null);
    fetch("/api/tree")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return (await r.json()) as { files: string[] };
      })
      .then((d) => {
        if (!cancelled) setFiles(d.files);
      })
      .catch((e: Error) => {
        if (!cancelled) setError(e.message);
      });
    return () => { cancelled = true; };
  }, [refreshKey]);

  const allExts = useMemo(() => {
    if (!files) return [] as Array<{ ext: string; count: number }>;
    const counts = new Map<string, number>();
    for (const f of files) {
      const e = fileExt(f);
      if (!e) continue;
      counts.set(e, (counts.get(e) ?? 0) + 1);
    }
    return [...counts.entries()]
      .map(([ext, count]) => ({ ext, count }))
      .sort((a, b) => a.ext.localeCompare(b.ext));
  }, [files]);

  const matcher = useMemo(() => buildMatcher(query), [query]);
  const queryBad = matcher === null;

  const filtered = useMemo(() => {
    if (!files) return [] as string[];
    const fn = matcher ?? (() => true);
    const exts = extFilter;
    return files.filter((f) => {
      if (exts.size > 0 && !exts.has(fileExt(f))) return false;
      return fn(f);
    });
  }, [files, matcher, extFilter]);

  const filterActive = query.trim().length > 0 || extFilter.size > 0;

  const tree = useMemo(() => buildTree(filtered, sort), [filtered, sort]);

  // When a filter is active, show every ancestor of a match — otherwise
  // matches deep in the tree are hidden inside collapsed dirs. Also
  // auto-inspect slideshow packages that contain a match so sealed
  // media files can surface under search.
  const effectiveExpanded = useMemo(() => {
    if (!filterActive) return expanded;
    const set = new Set(expanded);
    for (const f of filtered) for (const dir of ancestorDirs(f)) set.add(dir);
    return set;
  }, [expanded, filtered, filterActive]);

  const effectiveInspected = useMemo(() => {
    if (!filterActive) return inspectedPackages;
    const set = new Set(inspectedPackages);
    for (const f of filtered) {
      const parts = f.split("/");
      if (
        parts.length >= 3
        && PACKAGE_ROOTS.has(parts[0])
      ) {
        set.add(`${parts[0]}/${parts[1]}`);
      }
    }
    return set;
  }, [inspectedPackages, filtered, filterActive]);

  // When the active selection points at a page path (likely from
  // a wiki-sidebar click), expand the file-browser tree to reveal
  // that file and scroll it into view with a brief highlight.
  // Verifies wiki ↔ file sync visually — the file IS there, here's
  // where on disk.
  useEffect(() => {
    if (selection?.kind !== "page") return;
    const raw = selection.path;
    if (!raw) return;
    // selection paths arrive both as `wiki/foo.md` and `foo.md` —
    // normalise to the file-tree shape.
    const full = raw.startsWith("wiki/") ? raw : `wiki/${raw}`;
    setExpanded((cur) => {
      const next = new Set(cur);
      for (const a of ancestorDirs(full)) next.add(a);
      return next;
    });
    setRevealTick((t) => t + 1);
  }, [selection]);

  // Side-effect: after revealTick bumps, scroll the matching row
  // into view and add a transient pulse class.
  useEffect(() => {
    if (revealTick === 0) return;
    if (selection?.kind !== "page") return;
    const raw = selection.path;
    if (!raw) return;
    const full = raw.startsWith("wiki/") ? raw : `wiki/${raw}`;
    const tid = window.setTimeout(() => {
      const row = document.querySelector<HTMLElement>(
        `[data-fb-path="${cssEscapeAttr(full)}"]`,
      );
      if (!row) return;
      row.scrollIntoView({ behavior: "smooth", block: "center" });
      row.classList.add("sy-fb-row--pulse");
      window.setTimeout(() => row.classList.remove("sy-fb-row--pulse"), 1600);
    }, 60);
    return () => window.clearTimeout(tid);
  }, [revealTick, selection]);

  // Clamp the context menu inside the viewport. The raw
  // clientX/clientY at right-click can sit close enough to the
  // edges that the rendered menu spills off-screen (especially
  // near the bottom of the dock). After the first paint we
  // measure the box and shift it back into view with an 8px
  // breathing margin. Resets when the menu closes so the next
  // right-click hides → measures → shows cleanly.
  useLayoutEffect(() => {
    if (!menu) { setMenuPos(null); return; }
    const el = menuRef.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    const pad = 8;
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let x = menu.x;
    let y = menu.y;
    if (x + rect.width + pad > vw) x = Math.max(pad, vw - rect.width - pad);
    if (y + rect.height + pad > vh) y = Math.max(pad, vh - rect.height - pad);
    setMenuPos({ x, y });
  }, [menu]);

  // Close context menu on any click outside it.
  useEffect(() => {
    if (!menu) return;
    const onDoc = () => setMenu(null);
    window.addEventListener("click", onDoc);
    window.addEventListener("scroll", onDoc, true);
    return () => {
      window.removeEventListener("click", onDoc);
      window.removeEventListener("scroll", onDoc, true);
    };
  }, [menu]);

  // ESC dismisses the confirm dialog (Enter is intentionally NOT bound —
  // delete should require an explicit click on the danger button).
  useEffect(() => {
    if (!confirmDel) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !deleting) setConfirmDel(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [confirmDel, deleting]);

  // Click-outside dismiss for the filetype dropdown.
  useEffect(() => {
    if (!filterOpen) return;
    const onDoc = (e: MouseEvent) => {
      const t = e.target as HTMLElement;
      if (t && t.closest(".sy-fb-filter-pop")) return;
      if (t && t.closest(".sy-fb-filter-trigger")) return;
      setFilterOpen(false);
    };
    window.addEventListener("mousedown", onDoc);
    return () => window.removeEventListener("mousedown", onDoc);
  }, [filterOpen]);

  /** .docx import — fetch the binary, convert to markdown with
   *  mammoth (HTML) + turndown (HTML→md), then write to
   *  wiki/sources/<slug>.md via /api/page and open the result in
   *  the Editor. All client-side; no pandoc / LibreOffice
   *  dependency on the daemon side. */
  const importDocx = useCallback(async (path: string) => {
    flash(`importing ${path}…`);
    try {
      const fileRes = await fetch(
        `/api/fs/raw?path=${encodeURIComponent(path)}`,
      );
      if (!fileRes.ok) {
        flash(`docx import failed: HTTP ${fileRes.status}`);
        return;
      }
      const buf = await fileRes.arrayBuffer();
      // Dynamic imports so mammoth + turndown only load when the
      // user actually clicks a .docx — keeps the initial bundle
      // light for the common case of pure markdown editing.
      const [mammothMod, turndownMod] = await Promise.all([
        import("mammoth/mammoth.browser.js"),
        import("turndown"),
      ]);
      const mammoth = mammothMod.default ?? mammothMod;
      const TurndownService = turndownMod.default ?? turndownMod;
      const result = await mammoth.convertToHtml({ arrayBuffer: buf });
      const td = new TurndownService({
        headingStyle: "atx",
        bulletListMarker: "-",
        codeBlockStyle: "fenced",
        emDelimiter: "_",
      });
      const markdown = td.turndown(result.value).trim();

      const base = (path.split("/").pop() ?? "doc.docx")
        .replace(/\.docx$/i, "");
      const slug = base.toLowerCase().replace(/[^a-z0-9]+/g, "-")
        .replace(/^-+|-+$/g, "") || "doc";
      const today = new Date().toISOString().slice(0, 10);
      const fm = [
        "---",
        `title: "[src] ${base}"`,
        "type: source",
        `created: ${today}`,
        `updated: ${today}`,
        `extracted_from: ${path}`,
        "---",
        "",
      ].join("\n");
      const pageRel = `sources/${slug}.md`;
      const saveRes = await fetch("/api/page", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          path: pageRel,
          content: fm + "\n" + markdown + "\n",
        }),
      });
      if (!saveRes.ok) {
        flash(`docx import save failed: HTTP ${saveRes.status}`);
        return;
      }
      setSelection({ kind: "page", id: `sources/${slug}`, path: pageRel });
      switchToKind("markdown");
      flash(`imported as wiki/${pageRel}`);
    } catch (e) {
      flash(`docx import failed: ${(e as Error).message}`);
    }
  }, [setSelection, switchToKind]);

  const openSlideshow = useCallback((slug: string) => {
    if (!slug) return;
    notifyHtmlDeckOpen(slug);
    void fetch("/api/slideshows/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug }),
    }).then(() => {
      const focus = (tries: number) => {
        if (switchToKind("html-deck")) return;
        if (tries > 0) window.setTimeout(() => focus(tries - 1), 60);
      };
      focus(15);
    }).catch(() => { /* toast via server notice if any */ });
  }, [switchToKind]);

  const openReportDoc = useCallback((slug: string) => {
    if (!slug) return;
    window.dispatchEvent(new CustomEvent("sy:open-report-doc", {
      detail: { slug, title: slug },
    }));
    void fetch("/api/report-packages/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug }),
    }).then(() => {
      const focus = (tries: number) => {
        if (switchToKind("report-doc")) return;
        if (tries > 0) window.setTimeout(() => focus(tries - 1), 60);
      };
      focus(15);
    }).catch(() => {});
  }, [switchToKind]);

  const openWorksheet = useCallback((slug: string) => {
    if (!slug) return;
    void fetch("/api/worksheets/open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slug }),
    }).then(() => {
      const focus = (tries: number) => {
        if (switchToKind("univer")) return;
        if (tries > 0) window.setTimeout(() => focus(tries - 1), 60);
      };
      focus(15);
    }).catch(() => {});
  }, [switchToKind]);

  const openLibraryPackage = useCallback((path: string) => {
    const slug = packageSlugFromPath(path);
    if (!slug) return;
    const root = path.replace(/\/+$/, "").split("/")[0];
    if (root === "slideshows" || root === "decks") openSlideshow(slug);
    else if (root === "reports") openReportDoc(slug);
    else if (root === "worksheets") openWorksheet(slug);
  }, [openSlideshow, openReportDoc, openWorksheet]);

  const onClickFile = (path: string) => {
    const lower = path.toLowerCase();
    // .docx → browser-side mammoth → markdown → wiki/sources/<slug>.md.
    // Stage-3 successor to the pandoc-based /api/docx/import we
    // removed in Stage 1.
    if (lower.endsWith(".docx")) {
      void importDocx(path);
      return;
    }
    // Sealed library package (slideshow / report / worksheet).
    if (isLibraryPackage(path)) {
      openLibraryPackage(path);
      return;
    }
    if (isSlideshowEntryHtml(path)) {
      const slug = slideshowSlugFromPath(path);
      if (slug) {
        openSlideshow(slug);
        return;
      }
    }
    if (isReportEntry(path)) {
      const slug = packageSlugFromPath(path);
      if (slug) {
        openReportDoc(slug);
        return;
      }
    }
    // Non-entry files inside a package → Editor for text inspection.
    if (isInsideLibraryPackage(path) && isWorkspaceTextFile(path)) {
      setSelection({ kind: "page", id: path, path });
      switchToKind("markdown");
      return;
    }
    // wiki/.md files → set page selection AND flip to the Editor tab
    // so the user lands on the doc they clicked. Analyses, Sketch
    // decks and plain pages all route to Editor — the SketchTab
    // self-detects deck mode from the selection.
    if (path.startsWith("wiki/") && path.endsWith(".md")) {
      const slug = path.slice("wiki/".length, -".md".length);
      setSelection({ kind: "page", id: slug, path: path.slice("wiki/".length) });
      switchToKind("markdown");
      return;
    }
    // A sketch's PNG export — open the parent Sketch in the Sketch
    // tab so a click on the PNG produced by → Sketch deck actually
    // takes the user to its editable source. Both conventions: the
    // CE-native wiki/figures/_assets/ home and the legacy root
    // figures/ (pre-migration workspaces).
    if (
      (path.startsWith("wiki/figures/_assets/") || path.startsWith("figures/"))
      && (lower.endsWith(".png") || lower.endsWith(".svg"))
    ) {
      const base = path.split("/").pop() ?? "";
      const id = base.replace(/\.(png|svg)$/i, "");
      if (id) {
        setSelection({ kind: "sketch", id, name: id });
        switchToKind("sketch");
        return;
      }
    }
    // Any image elsewhere — set a page selection so the inline
    // image preview in the Editor's read view picks it up. Beats
    // a silent "no viewer" toast for the common case (opening a
    // raster from `vault/raw/` or similar).
    const IMAGE_EXTS = [".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"];
    if (IMAGE_EXTS.some((ext) => lower.endsWith(ext))) {
      setSelection({ kind: "page", id: path, path });
      switchToKind("markdown");
      return;
    }
    // Any other text-shaped file → open it in the Editor tab as
    // code (CodeMirror picks the language from the extension /
    // first-line shebang).
    const TEXT_EXTS = [
      ".py", ".pyw",
      ".js", ".mjs", ".cjs", ".jsx", ".ts", ".tsx",
      ".html", ".htm", ".css",
      ".json", ".jsonl", ".geojson",
      ".rs", ".go", ".swift", ".rb", ".rake",
      ".sh", ".bash", ".zsh", ".fish",
      ".toml", ".yaml", ".yml", ".ini", ".env",
      ".txt", ".log", ".csv", ".tsv",
      ".sql",
      ".md", ".mdx", ".markdown",  // non-wiki .md still wants the editor
    ];
    const SPECIAL_NAMES = ["gemfile", "rakefile", "makefile", "dockerfile"];
    const base = lower.split("/").pop() ?? "";
    if (
      TEXT_EXTS.some((ext) => lower.endsWith(ext))
      || SPECIAL_NAMES.includes(base)
    ) {
      // Selection-as-page works fine — EditorTab branches on the
      // path's wiki/.md shape internally to pick the right
      // fetch/save endpoint. The id field is unused for non-wiki
      // files but kept set to the path for symmetry.
      setSelection({ kind: "page", id: path, path });
      switchToKind("markdown");
      return;
    }
    flash("no viewer for this file kind yet");
  };

  const flash = (m: string) => {
    setToast(m);
    setTimeout(() => setToast((t) => (t === m ? null : t)), 1800);
  };

  /** Execute a pack-declared file route. The pattern: optional
   *  POST to `route.endpoint` with `{path}`, then switch to
   *  `route.tab_kind`, and (when the response carries a payload
   *  + selection_kind is set) drop the response into the
   *  selection layer so the target tab picks up the data.
   *
   *  Today this covers the LibreOffice pack's pptx → image-deck
   *  and docx → markdown flows that previously lived as
   *  hard-coded branches inside FileBrowser. The legacy code
   *  paths still run for files without a pack route, so adding
   *  a pack is purely additive — no breakage if the pack is
   *  uninstalled. */
  const runFileRoute = async (route: FileRoute, path: string) => {
    flash(`${route.label ?? route.action}…`);
    try {
      let body: Record<string, unknown> | null = null;
      if (route.endpoint) {
        const r = await fetch(
          `${route.endpoint}?path=${encodeURIComponent(path)}`,
          // GET first; some endpoints (pptx) take a query param,
          // others (docx/import) want a POST body. Try the
          // POST shape if GET 404s or 405s.
        );
        if (r.ok) {
          body = await r.json();
        } else if (r.status === 404 || r.status === 405) {
          const r2 = await fetch(route.endpoint, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ path }),
          });
          if (!r2.ok) {
            const eb = await r2.json().catch(() => ({} as Record<string, unknown>));
            flash(`${route.action} failed: ${eb.error ?? eb.detail ?? r2.status}`);
            return;
          }
          body = await r2.json();
        } else {
          const eb = await r.json().catch(() => ({} as Record<string, unknown>));
          flash(`${route.action} failed: ${eb.error ?? eb.detail ?? r.status}`);
          return;
        }
      }
      // Async pack action: the endpoint dispatched a background agent
      // (returns {run_id}) rather than a synchronous result. Route to
      // the Agent Dashboard to watch it — don't open an empty tab, and
      // don't re-fire on every click.
      if (body?.run_id) {
        flash(`${route.label ?? route.action} started — see Agents`);
        window.dispatchEvent(new CustomEvent("sy:open-agents-run", {
          detail: { run_id: String(body.run_id) },
        }));
        return;
      }
      // Selection handling per route kind. image-deck (the pptx
      // path) needs the slide list constructed from the response;
      // page (docx import) needs the new wiki path. Generic
      // selection_kind:csv flows through as a file-path
      // selection. Anything else just switches tabs.
      if (route.selection_kind === "page" && body?.page_path) {
        const pagePath = String(body.page_path);
        const id = pagePath.startsWith("wiki/")
          ? pagePath.slice("wiki/".length, -".md".length)
          : pagePath;
        setSelection({ kind: "page", id, path: pagePath });
      }
      if (route.tab_kind) {
        switchToKind(route.tab_kind);
      }
    } catch (e) {
      flash(`${route.action} failed: ${(e as Error).message}`);
    }
  };

  const ops = {
    copyPath: async (path: string) => {
      try {
        await navigator.clipboard.writeText(path);
        flash(`copied: ${path}`);
      } catch {
        flash("clipboard blocked");
      }
    },
    reveal: async (path: string) => {
      const r = await fetch("/api/fs/reveal", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!r.ok) flash(`reveal failed: ${(await r.json()).error}`);
    },
    openExternal: async (path: string) => {
      flash(`opening ${path}…`);
      try {
        const r = await fetch("/api/fs/open-external", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ path }),
        });
        if (!r.ok) {
          const body = await r.json().catch(() => ({}));
          flash(`open failed: ${body.error ?? r.status}`);
        }
      } catch (e) {
        flash(`open failed: ${(e as Error).message}`);
      }
    },
    duplicate: async (path: string) => {
      const r = await fetch("/api/fs/duplicate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!r.ok) {
        flash(`duplicate failed: ${(await r.json()).error}`);
        return;
      }
      const { path: newPath } = await r.json();
      flash(`duplicated → ${newPath}`);
      await reload();
    },
    // Open the styled confirm dialog. Actual API call happens after the
    // user clicks Delete in `confirmDelete`.
    deleteFile: (path: string) => setConfirmDel(path),
  };

  const confirmDelete = async () => {
    const path = confirmDel;
    if (!path) return;
    setDeleting(true);
    try {
      const r = await fetch("/api/fs/delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      if (!r.ok) {
        flash(`delete failed: ${(await r.json()).error}`);
        return;
      }
      if (
        selection?.kind === "page" &&
        (selection.path === path || `wiki/${selection.path}` === path)
      ) {
        setSelection(null);
      }
      const b = await r.json().catch(() => ({} as { trashed_to?: string }));
      flash(`moved to ${b.trashed_to ?? "trash"}: ${path}`);
      await reload();
    } finally {
      setDeleting(false);
      setConfirmDel(null);
    }
  };

  const reload = async () => {
    try {
      const r = await fetch("/api/tree");
      if (!r.ok) {
        flash(`couldn't refresh the file list: HTTP ${r.status}`);
        return;
      }
      setFiles(((await r.json()) as { files: string[] }).files);
    } catch (e) {
      flash(`couldn't refresh the file list: ${(e as Error).message}`);
    }
  };

  const toggle = (path: string) => {
    setExpanded((cur) => {
      const next = new Set(cur);
      if (next.has(path)) next.delete(path);
      else next.add(path);
      return next;
    });
  };

  const setPackageInspected = (path: string, on: boolean) => {
    setInspectedPackages((cur) => {
      const next = new Set(cur);
      if (on) next.add(path);
      else next.delete(path);
      return next;
    });
    if (on) {
      // Also expand the package dir so children render.
      setExpanded((cur) => {
        const next = new Set(cur);
        next.add(path);
        // Ensure parent slideshows/ is expanded too.
        const parent = path.includes("/") ? path.split("/")[0] : "";
        if (parent) next.add(parent);
        return next;
      });
    }
  };

  const renderNode = (node: FileNode, depth: number): React.ReactNode => {
    const isPkg = node.isDir && isLibraryPackage(node.path);
    const isInspected = isPkg && effectiveInspected.has(node.path);
    const isExpanded = effectiveExpanded.has(node.path);
    // Sealed packages only show children when inspected.
    const showChildren =
      node.isDir
      && isExpanded
      && (!isPkg || isInspected)
      && node.children.length > 0;
    const isSelected =
      selection?.kind === "page" &&
      (`wiki/${selection.path}` === node.path || selection.path === node.path);
    const onContext = (ev: React.MouseEvent) => {
      ev.preventDefault();
      ev.stopPropagation();
      setMenu({ x: ev.clientX, y: ev.clientY, path: node.path, isDir: node.isDir });
    };
    const onRowClick = () => {
      if (isPkg) {
        // Primary action: open the slideshow (not expand).
        onClickFile(node.path);
        return;
      }
      if (node.isDir) {
        toggle(node.path);
        return;
      }
      onClickFile(node.path);
    };
    let glyph: string;
    if (isPkg) {
      glyph = isInspected && isExpanded ? "▾" : "▦";
    } else if (node.isDir) {
      glyph = isExpanded ? "▾" : "▸";
    } else {
      glyph = "·";
    }
    return (
      <div key={node.path}>
        <button
          type="button"
          className={
            "sy-fb-row"
            + (isSelected ? " sy-fb-row--active" : "")
            + (isPkg ? " sy-fb-row--package" : "")
          }
          style={{ paddingLeft: 8 + depth * 12 }}
          data-fb-path={node.path}
          onClick={onRowClick}
          onContextMenu={onContext}
          title={
            isPkg
              ? `${node.path}  ·  click to open slideshow · right-click for contents`
              : node.path
          }
        >
          <span className="sy-fb-glyph">{glyph}</span>
          <span className="sy-fb-name">{node.name}</span>
        </button>
        {showChildren && node.children.map((c) => renderNode(c, depth + 1))}
      </div>
    );
  };

  const toggleExt = (ext: string) => {
    setExtFilter((cur) => {
      const next = new Set(cur);
      if (next.has(ext)) next.delete(ext);
      else next.add(ext);
      return next;
    });
  };

  return (
    <div className="sy-fb">
      <div className="sy-fb-head">
        {headExtra ?? <span>FILES</span>}
        {filterActive && files && (
          <span className="sy-fb-count">
            {filtered.length}/{files.length}
          </span>
        )}
      </div>
      <div className="sy-fb-controls">
        <input
          type="search"
          className={"sy-fb-search" + (queryBad ? " sy-fb-search--bad" : "")}
          placeholder="search · *.ext · /regex/"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          spellCheck={false}
          title={
            queryBad
              ? "invalid regex"
              : "plain text (substring) · *.pdf (filetype) · /pat/flags (regex)"
          }
        />
        <button
          type="button"
          className="sy-fb-ctrl"
          onClick={() => setSort((s) => (s === "asc" ? "desc" : "asc"))}
          title={`sort: name ${sort === "asc" ? "ascending" : "descending"} (click to flip)`}
        >
          A{sort === "asc" ? "↓" : "↑"}
        </button>
        <button
          type="button"
          className={
            "sy-fb-ctrl sy-fb-filter-trigger" +
            (extFilter.size > 0 ? " sy-fb-ctrl--active" : "")
          }
          onClick={() => setFilterOpen((o) => !o)}
          title="filter by file type"
        >
          ⌅{extFilter.size > 0 ? ` ${extFilter.size}` : ""}
        </button>
        {filterOpen && (
          <div className="sy-fb-filter-pop" role="menu">
            <div className="sy-fb-filter-head">
              File types
              {extFilter.size > 0 && (
                <button
                  type="button"
                  className="sy-fb-filter-clear"
                  onClick={() => setExtFilter(new Set())}
                >
                  Clear
                </button>
              )}
            </div>
            {allExts.length === 0 && <div className="sy-fb-empty">no files</div>}
            {allExts.map(({ ext, count }) => (
              <label key={ext} className="sy-fb-filter-row">
                <input
                  type="checkbox"
                  checked={extFilter.has(ext)}
                  onChange={() => toggleExt(ext)}
                />
                <span className="sy-fb-filter-ext">.{ext}</span>
                <span className="sy-fb-filter-count">{count}</span>
              </label>
            ))}
          </div>
        )}
      </div>
      {error && <div className="sy-fb-error">error: {error}</div>}
      {!files && !error && <div className="sy-fb-empty">loading…</div>}
      {files && (
        <div className="sy-fb-tree">
          {tree.length === 0 && filterActive && (
            <div className="sy-fb-empty">no matches</div>
          )}
          {tree.map((n) => renderNode(n, 0))}
        </div>
      )}
      {menu && (() => {
        const menuIsPkg = menu.isDir && isLibraryPackage(menu.path);
        const menuPkgInspected = menuIsPkg && inspectedPackages.has(menu.path);
        const openable = canOpenInSwitchbay(menu.path, menu.isDir);
        return (
        <div
          ref={menuRef}
          className="sy-fb-menu"
          style={{
            top: (menuPos ?? menu).y,
            left: (menuPos ?? menu).x,
            // Hide on the very first frame (before the layout
            // effect runs) so a too-low / too-right click doesn't
            // briefly flash a partially-off-screen menu.
            visibility: menuPos ? "visible" : "hidden",
          }}
          onClick={(ev) => ev.stopPropagation()}
        >
          {(openable || menuIsPkg) && (
            <button
              onClick={() => {
                if (menuIsPkg || canOpenInSwitchbay(menu.path, menu.isDir)) {
                  onClickFile(menu.path);
                } else {
                  flash(
                    "no Switch Bay viewer for this file kind — try Open to use the system default",
                  );
                }
                setMenu(null);
              }}
              disabled={!openable && !menuIsPkg}
              title={
                menuIsPkg
                  ? "Open this HTML slideshow in the Slideshow tab"
                  : isSlideshowEntryHtml(menu.path)
                    ? "Open the slideshow in the Slideshow tab"
                    : openable
                      ? "Open in the matching Switch Bay tab"
                      : "No internal viewer for this file kind"
              }
            >
              Open in Switch Bay
            </button>
          )}
          {/* Package contents: meta/json open as code, not the viewer. */}
          {!menu.isDir
            && isInsideLibraryPackage(menu.path)
            && !isSlideshowEntryHtml(menu.path)
            && !isReportEntry(menu.path)
            && isWorkspaceTextFile(menu.path) && (
            <button
              onClick={() => {
                setSelection({ kind: "page", id: menu.path, path: menu.path });
                switchToKind("markdown");
                setMenu(null);
              }}
              title="Open as a text file in the Editor (via /api/file)"
            >
              Open in Editor
            </button>
          )}
          {menuIsPkg && (
            <button
              onClick={() => {
                const next = !menuPkgInspected;
                setPackageInspected(menu.path, next);
                if (next) {
                  flash("showing package contents — hide via right-click again");
                }
                setMenu(null);
              }}
              title={
                menuPkgInspected
                  ? "Hide index.html, media, deck.json under this slideshow"
                  : "Expand this folder to inspect HTML, media, and deck.json"
              }
            >
              {menuPkgInspected ? "Hide package contents" : "Show package contents"}
            </button>
          )}
          {/* Pack-declared actions for this file's extension.
            * Each route comes from a Manifest.file_routes entry —
            * the LibreOffice pack contributes pptx/docx/etc.,
            * future packs (Vega-Lite spec authoring, mermaid
            * renderers, …) can hang their own handlers off the
            * same surface without core changes. */}
          {!menu.isDir && (() => {
            // fileExt returns "pptx" (no leading dot); route map
            // keys are ".pptx". Prepend so the lookup hits.
            const bare = fileExt(menu.path);
            const ext = bare ? "." + bare : "";
            const routes = fileRoutes.get(ext) ?? [];
            return routes.map((route) => (
              <button
                key={route.action}
                onClick={() => {
                  void runFileRoute(route, menu.path);
                  setMenu(null);
                }}
                title={
                  route.description
                  ?? `${route.action} (from pack ${route.pack ?? "?"})`
                }
              >
                {route.label ?? route.action}
              </button>
            ));
          })()}
          {!menu.isDir && (
            <button
              onClick={() => { void ops.openExternal(menu.path); setMenu(null); }}
              title="Open with the system default app (Preview / Word / image viewer / …)"
            >
              Open
            </button>
          )}
          {!menu.isDir && (
            <button
              onClick={() => {
                // The file is already inside the workspace — no need to
                // re-upload via /api/chat/upload. Just hand the path to
                // the rail; its agent can Read it directly.
                window.dispatchEvent(new CustomEvent("sy:attach-path", {
                  detail: { path: menu.path },
                }));
                flash(`added to chat · ${menu.path}`);
                setMenu(null);
              }}
            >
              Add to chat
            </button>
          )}
          <button onClick={() => { ops.copyPath(menu.path); setMenu(null); }}>Copy path</button>
          <button
            onClick={() => { void ops.reveal(menu.path); setMenu(null); }}
            title="Reveal this path in Finder"
          >
            Reveal in Finder
          </button>
          {!menu.isDir && (
            <button onClick={() => { ops.duplicate(menu.path); setMenu(null); }}>Duplicate</button>
          )}
          {!menu.isDir && (
            <button
              className="sy-fb-menu-danger"
              onClick={() => { ops.deleteFile(menu.path); setMenu(null); }}
            >
              Delete
            </button>
          )}
        </div>
        );
      })()}
      {toast && <div className="sy-fb-toast">{toast}</div>}
      {confirmDel && (
        <div
          className="sy-confirm-backdrop"
          onClick={() => !deleting && setConfirmDel(null)}
        >
          <div
            className="sy-confirm"
            role="alertdialog"
            aria-labelledby="sy-confirm-title"
            onClick={(ev) => ev.stopPropagation()}
          >
            <div id="sy-confirm-title" className="sy-confirm-title">Delete file?</div>
            <div className="sy-confirm-body">
              This moves{" "}
              <code className="sy-confirm-path">{confirmDel}</code> to the
              Trash — restore from there if you change your mind.
              {confirmDel.startsWith("wiki/") && (
                <> The graph will rebuild automatically.</>
              )}
            </div>
            <div className="sy-confirm-actions">
              <button
                type="button"
                className="sy-confirm-btn"
                onClick={() => setConfirmDel(null)}
                disabled={deleting}
                autoFocus
              >
                Cancel
              </button>
              <button
                type="button"
                className="sy-confirm-btn sy-confirm-btn--danger"
                onClick={confirmDelete}
                disabled={deleting}
              >
                {deleting ? "Deleting…" : "Delete"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
