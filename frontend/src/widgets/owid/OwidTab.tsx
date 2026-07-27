import { useEffect, useState } from "react";

type Chart = { slug: string; title: string; topic: string };

/**
 * OWID browse tab (from the `owid` pack). Search the starter catalogue
 * or paste any grapher slug / URL, then Import — the daemon fetches the
 * chart's data into `data/owid/<slug>.csv` and authors a starter plot,
 * then jumps to the Plot tab.
 */
export default function OwidTab() {
  const [q, setQ] = useState("");
  const [charts, setCharts] = useState<Chart[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [custom, setCustom] = useState("");
  const [note, setNote] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    let live = true;
    fetch(`/api/owid/search?q=${encodeURIComponent(q)}`)
      .then((r) => (r.ok ? r.json() : { charts: [] }))
      .then((b: { charts: Chart[] }) => { if (live) setCharts(b.charts || []); })
      .catch(() => { if (live) setCharts([]); });
    return () => { live = false; };
  }, [q]);

  const doImport = async (slug: string) => {
    if (busy) return;
    setBusy(slug);
    setNote(null);
    try {
      const r = await fetch("/api/owid/import", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ slug }),
      });
      const b = await r.json();
      if (!r.ok) {
        setNote({ kind: "err", text: b.error || "import failed" });
      } else {
        setNote({ kind: "ok", text: `Imported “${b.title}” (${b.rows.toLocaleString()} rows) → Plot tab. CSV at ${b.csv_path}.` });
      }
    } catch (e) {
      setNote({ kind: "err", text: String((e as Error).message || e) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="sy-owid">
      <div className="sy-owid-head">
        <h2>Our World in Data</h2>
        <p>Browse a chart and import its data — it lands as a CSV in the
          workspace and opens as a plot you can refine.</p>
      </div>

      <div className="sy-owid-custom">
        <input
          type="text"
          placeholder="Paste any grapher slug or URL (e.g. life-expectancy)…"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && custom.trim()) void doImport(custom.trim()); }}
        />
        <button
          type="button"
          className="sy-owid-import"
          disabled={!custom.trim() || busy !== null}
          onClick={() => void doImport(custom.trim())}
        >
          Import
        </button>
      </div>

      {note && (
        <div className={"sy-owid-note sy-owid-note--" + note.kind}>{note.text}</div>
      )}

      <input
        type="search"
        className="sy-owid-search"
        placeholder="Filter the starter catalogue…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
      />

      <div className="sy-owid-list">
        {charts.length === 0 && (
          <div className="sy-owid-empty">No matching charts — try pasting a grapher URL above.</div>
        )}
        {charts.map((c) => (
          <div className="sy-owid-row" key={c.slug}>
            <div className="sy-owid-row-main">
              <span className="sy-owid-title">{c.title}</span>
              <span className="sy-owid-topic">{c.topic}</span>
              <span className="sy-owid-slug">{c.slug}</span>
            </div>
            <button
              type="button"
              className="sy-owid-import"
              disabled={busy !== null}
              onClick={() => void doImport(c.slug)}
            >
              {busy === c.slug ? "importing…" : "Import"}
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
