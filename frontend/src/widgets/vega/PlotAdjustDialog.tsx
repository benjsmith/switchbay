import { useState } from "react";
import { useEscToClose } from "../../lib/useEscToClose";

/* eslint-disable @typescript-eslint/no-explicit-any */
type Plot = { id: string; name: string; spec: Record<string, any> };

type ChannelForm = {
  title: string; log: boolean; min: string; max: string; ticks: string;
};

function readChannel(enc: any, ch: string): ChannelForm {
  const c = (enc && enc[ch]) || {};
  const scale = c.scale || {};
  const axis = c.axis || {};
  const dom = Array.isArray(scale.domain) ? scale.domain : [];
  const curMin = typeof scale.domainMin === "number" ? scale.domainMin
    : (dom.length === 2 ? dom[0] : null);
  const curMax = typeof scale.domainMax === "number" ? scale.domainMax
    : (dom.length === 2 ? dom[1] : null);
  return {
    title: typeof axis.title === "string" ? axis.title : "",
    log: scale.type === "log",
    min: curMin === null ? "" : String(curMin),
    max: curMax === null ? "" : String(curMax),
    ticks: typeof axis.tickCount === "number" ? String(axis.tickCount) : "",
  };
}

function applyChannel(enc: any, ch: string, f: ChannelForm): void {
  const c = { ...(enc[ch] || {}) };
  const scale = { ...(c.scale || {}) };
  const axis = { ...(c.axis || {}) };
  if (f.log) {
    scale.type = "log";
    scale.zero = false;       // log can't include zero; also silences the warning
  } else {
    if (scale.type === "log") delete scale.type;
    if (scale.zero === false) delete scale.zero;
  }
  // Independent min/max via domainMin/domainMax so either side works
  // alone. Clear any prior explicit `domain` we might have written.
  delete scale.domain;
  const min = f.min.trim() === "" ? null : Number(f.min);
  if (min !== null && !Number.isNaN(min)) scale.domainMin = min;
  else delete scale.domainMin;
  const max = f.max.trim() === "" ? null : Number(f.max);
  if (max !== null && !Number.isNaN(max)) scale.domainMax = max;
  else delete scale.domainMax;
  const t = f.ticks.trim() === "" ? null : Number(f.ticks);
  if (t !== null && !Number.isNaN(t)) axis.tickCount = t; else delete axis.tickCount;
  if (f.title.trim() !== "") axis.title = f.title; else delete axis.title;
  if (Object.keys(scale).length) c.scale = scale; else delete c.scale;
  if (Object.keys(axis).length) c.axis = axis; else delete c.axis;
  enc[ch] = c;
}

function ChannelFields(props: {
  label: string; form: ChannelForm; set: (f: ChannelForm) => void;
}) {
  const { label, form, set } = props;
  return (
    <fieldset className="sy-adj-field">
      <legend>{label} axis</legend>
      <label className="sy-adj-row">
        <span>Title</span>
        <input type="text" value={form.title} placeholder="(default)"
          onChange={(e) => set({ ...form, title: e.target.value })} />
      </label>
      <label className="sy-adj-row sy-adj-check">
        <input type="checkbox" checked={form.log}
          onChange={(e) => set({ ...form, log: e.target.checked })} />
        <span>Logarithmic <em>(needs positive values)</em></span>
      </label>
      <div className="sy-adj-row sy-adj-triple">
        <label><span>Min</span>
          <input type="number" value={form.min} placeholder="auto"
            onChange={(e) => set({ ...form, min: e.target.value })} /></label>
        <label><span>Max</span>
          <input type="number" value={form.max} placeholder="auto"
            onChange={(e) => set({ ...form, max: e.target.value })} /></label>
        <label><span>Ticks</span>
          <input type="number" value={form.ticks} placeholder="auto" min="1"
            onChange={(e) => set({ ...form, ticks: e.target.value })} /></label>
      </div>
    </fieldset>
  );
}

/**
 * Structured plot-settings dialog (the ⚙ on a plot card). Edits the
 * Vega-Lite spec's axis scales / domains / ticks / titles without
 * touching raw JSON, then either overwrites the plot or saves the
 * adjusted version as a new one.
 */
export default function PlotAdjustDialog(props: {
  plot: Plot;
  onClose: () => void;
  onApplied: (selection: { id: string; name: string } | null) => void;
}) {
  const { plot, onClose, onApplied } = props;
  useEscToClose(onClose);
  const enc0 = plot.spec?.encoding || {};
  const [chartTitle, setChartTitle] = useState<string>(
    typeof plot.spec?.title === "string" ? plot.spec.title : "");
  const [x, setX] = useState<ChannelForm>(readChannel(enc0, "x"));
  const [y, setY] = useState<ChannelForm>(readChannel(enc0, "y"));
  const [busy, setBusy] = useState<"" | "current" | "new">("");
  const [error, setError] = useState<string | null>(null);

  const buildSpec = (): Record<string, any> => {
    const spec = JSON.parse(JSON.stringify(plot.spec || {}));
    const enc = spec.encoding = spec.encoding || {};
    applyChannel(enc, "x", x);
    applyChannel(enc, "y", y);
    if (chartTitle.trim() !== "") spec.title = chartTitle; else delete spec.title;
    return spec;
  };

  const apply = async (mode: "current" | "new") => {
    if (busy) return;
    setBusy(mode);
    setError(null);
    const spec = buildSpec();
    const payload = mode === "current"
      ? { id: plot.id, name: plot.name, spec }
      : { name: `${plot.name} (adjusted)`, spec };
    try {
      const r = await fetch("/api/plot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!r.ok) { setError(`save failed: HTTP ${r.status}`); setBusy(""); return; }
      const j = (await r.json()) as { plot: { id: string; name: string } };
      onApplied(mode === "new"
        ? (j.plot ? { id: j.plot.id, name: j.plot.name } : null)
        : { id: plot.id, name: plot.name });
      onClose();
    } catch (e) {
      setError(String((e as Error).message || e));
      setBusy("");
    }
  };

  return (
    <div className="sy-plot-editor-backdrop" onClick={onClose}>
      <div className="sy-plot-editor sy-adj" role="dialog"
        aria-label="Adjust plot" onClick={(e) => e.stopPropagation()}>
        <header className="sy-plot-editor-head">
          <span className="sy-plot-editor-title">Adjust · <strong>{plot.name}</strong></span>
          <span className="sy-plot-editor-hint">axes, scale, ticks, titles</span>
        </header>
        <div className="sy-adj-body">
          <label className="sy-adj-row">
            <span>Chart title</span>
            <input type="text" value={chartTitle} placeholder="(none)"
              onChange={(e) => setChartTitle(e.target.value)} />
          </label>
          <ChannelFields label="X" form={x} set={setX} />
          <ChannelFields label="Y" form={y} set={setY} />
          {error && <div className="sy-plot-editor-err">{error}</div>}
        </div>
        <footer className="sy-plot-editor-foot">
          <button type="button" className="sy-vega-toolbar-btn"
            onClick={onClose} disabled={busy !== ""}>Cancel</button>
          <span className="sy-spacer" />
          <button type="button" className="sy-vega-toolbar-btn"
            onClick={() => void apply("new")} disabled={busy !== ""}
            title="Save a new plot with these settings; the original is untouched">
            {busy === "new" ? "…" : "Apply as new"}</button>
          <button type="button" className="sy-vega-toolbar-btn sy-vega-toolbar-btn--primary"
            onClick={() => void apply("current")} disabled={busy !== ""}
            title="Overwrite this plot with these settings">
            {busy === "current" ? "…" : "Apply (overwrite)"}</button>
        </footer>
      </div>
    </div>
  );
}
