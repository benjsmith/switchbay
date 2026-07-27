import { useCallback, useEffect, useMemo, useState } from "react";
import { useTabs } from "../../center/TabsContext";
import { notifyHtmlDeckOpen } from "../htmldeck/htmlDeckOpen";
import { notifyReportDocOpen } from "./reportDocOpen";

type LibItem = {
  kind: string;
  slug: string;
  title: string;
  summary?: string;
  path?: string;
  thumbs?: string[];
  sheet_names?: string[];
  updated_at?: number;
  wikilink?: string;
};

type LibraryPayload = {
  reports: LibItem[];
  slideshows: LibItem[];
  worksheets: LibItem[];
  counts: { reports: number; slideshows: number; worksheets: number };
};

const VISIBLE = 3;

function CarouselRow({
  label,
  items,
  onOpen,
  emptyHint,
}: {
  label: string;
  items: LibItem[];
  onOpen: (item: LibItem) => void;
  emptyHint: string;
}) {
  const [offset, setOffset] = useState(0);
  const [thumbIdx, setThumbIdx] = useState<Record<string, number>>({});

  const maxOff = Math.max(0, items.length - VISIBLE);
  const slice = items.slice(offset, offset + VISIBLE);

  const cycleThumb = (slug: string, delta: number, n: number) => {
    if (n <= 0) return;
    setThumbIdx((cur) => {
      const i = cur[slug] ?? 0;
      return { ...cur, [slug]: (i + delta + n) % n };
    });
  };

  return (
    <section className="sy-lib-row">
      <header className="sy-lib-row-head">
        <h2>{label}</h2>
        <span className="sy-lib-count">{items.length}</span>
        <div className="sy-lib-nav">
          <button
            type="button"
            disabled={offset <= 0}
            onClick={() => setOffset((o) => Math.max(0, o - 1))}
            aria-label="Previous"
          >
            ‹
          </button>
          <button
            type="button"
            disabled={offset >= maxOff}
            onClick={() => setOffset((o) => Math.min(maxOff, o + 1))}
            aria-label="Next"
          >
            ›
          </button>
        </div>
      </header>
      {items.length === 0 ? (
        <p className="sy-lib-empty">{emptyHint}</p>
      ) : (
        <div className="sy-lib-cards">
          {slice.map((item) => {
            const thumbs = item.thumbs || [];
            const ti = thumbIdx[item.slug] ?? 0;
            const thumb = thumbs[ti];
            const sheets = item.sheet_names || [];
            return (
              <article key={`${item.kind}:${item.slug}`} className="sy-lib-card">
                <div className="sy-lib-thumb">
                  {thumb ? (
                    <img src={thumb} alt="" />
                  ) : (
                    <div className="sy-lib-monogram">
                      {(item.title || item.slug).slice(0, 1).toUpperCase()}
                    </div>
                  )}
                  {(thumbs.length > 1 || sheets.length > 1) && (
                    <div className="sy-lib-thumb-nav">
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          cycleThumb(
                            item.slug, -1,
                            Math.max(thumbs.length, sheets.length, 1),
                          );
                        }}
                      >
                        ‹
                      </button>
                      <span>
                        {sheets.length > 1
                          ? (sheets[ti % sheets.length] || "")
                          : `${(ti % Math.max(thumbs.length, 1)) + 1}/${Math.max(thumbs.length, 1)}`}
                      </span>
                      <button
                        type="button"
                        onClick={(e) => {
                          e.stopPropagation();
                          cycleThumb(
                            item.slug, 1,
                            Math.max(thumbs.length, sheets.length, 1),
                          );
                        }}
                      >
                        ›
                      </button>
                    </div>
                  )}
                </div>
                <button
                  type="button"
                  className="sy-lib-card-body"
                  onClick={() => onOpen(item)}
                >
                  <div className="sy-lib-card-title">{item.title}</div>
                  {item.summary && (
                    <div className="sy-lib-card-sum">{item.summary}</div>
                  )}
                  <div className="sy-lib-card-meta">
                    {item.kind}
                    {item.updated_at
                      ? ` · ${new Date(item.updated_at * 1000).toLocaleDateString()}`
                      : ""}
                  </div>
                </button>
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}

export default function LibraryTab() {
  const { switchToKind } = useTabs();
  const [data, setData] = useState<LibraryPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<LibItem[] | null>(null);

  const reload = useCallback(() => {
    setError(null);
    fetch("/api/library")
      .then(async (r) => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json() as Promise<LibraryPayload>;
      })
      .then(setData)
      .catch((e: Error) => setError(e.message));
  }, []);

  useEffect(() => { reload(); }, [reload]);

  useEffect(() => {
    const t = window.setTimeout(() => {
      const query = q.trim();
      if (!query) {
        setHits(null);
        return;
      }
      fetch(`/api/library/search?q=${encodeURIComponent(query)}`)
        .then((r) => (r.ok ? r.json() : null))
        .then((b) => setHits((b?.hits as LibItem[]) || []))
        .catch(() => setHits([]));
    }, 120);
    return () => window.clearTimeout(t);
  }, [q]);

  const openItem = useCallback((item: LibItem) => {
    if (item.kind === "slideshow") {
      notifyHtmlDeckOpen(item.slug, item.title);
      void fetch("/api/slideshows/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug: item.slug }),
      }).then(() => switchToKind("html-deck"));
    } else if (item.kind === "report") {
      notifyReportDocOpen(item.slug, item.title);
      void fetch("/api/report-packages/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug: item.slug }),
      }).then(() => switchToKind("report-doc"));
    } else if (item.kind === "worksheet") {
      void fetch("/api/worksheets/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug: item.slug }),
      }).then(() => switchToKind("univer"));
    }
  }, [switchToKind]);

  const filtered = useMemo(() => {
    if (!data) return null;
    if (!hits) return data;
    const byKind = (k: string) => hits.filter((h) => h.kind === k);
    return {
      reports: byKind("report"),
      slideshows: byKind("slideshow"),
      worksheets: byKind("worksheet"),
      counts: data.counts,
    };
  }, [data, hits]);

  return (
    <div className="sy-lib">
      <header className="sy-lib-head">
        <div>
          <h1>Library</h1>
          <p className="sy-lib-sub">
            Durable reports, slideshows, and worksheets — sealed packages
            outside the wiki.
          </p>
        </div>
        <input
          type="search"
          className="sy-lib-search"
          placeholder="Search library…"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          spellCheck={false}
        />
      </header>
      {error && <div className="sy-lib-error">error: {error}</div>}
      {!filtered && !error && <div className="sy-lib-empty">loading…</div>}
      {filtered && (
        <>
          <CarouselRow
            label="Reports"
            items={filtered.reports}
            onOpen={openItem}
            emptyHint="No durable reports yet. Promote an agent Report or write reports/<slug>/."
          />
          <CarouselRow
            label="Slideshows"
            items={filtered.slideshows}
            onOpen={openItem}
            emptyHint="No slideshows. Author MD then /slideshow from-md notes/deck.md."
          />
          <CarouselRow
            label="Worksheets"
            items={filtered.worksheets}
            onOpen={openItem}
            emptyHint="No named worksheets. In Sheet use Save as worksheet…"
          />
        </>
      )}
    </div>
  );
}
