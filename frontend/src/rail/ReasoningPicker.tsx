import { useCallback, useEffect, useRef, useState } from "react";

/**
 * Reasoning-effort control — the third picker dimension, after provider
 * and model.
 *
 * The same weights are a different cost/latency tool at different
 * efforts, so effort belongs next to the composer rather than buried in
 * Settings: it's a per-message decision ("just fix this cell" vs "work
 * out the migration"), not a preference you set once.
 *
 * Options are read from the daemon PER MODEL, never hardcoded here —
 * a provider's reasoning models and its plain ones take different
 * values, and some take none at all. An empty list renders nothing, so
 * the control is simply absent on models that can't vary.
 *
 * Sits to the left of the mic in the composer's bottom-right corner and
 * opens upward, so it never covers the text you're typing.
 */

type Option = { id: string; label: string; hint?: string };

type OptionsResponse = {
  provider: string;
  model: string | null;
  options: Option[];
  selected: string | null;
};

/** Refetch cue — ProviderPicker fires this after changing provider/model. */
export const LLM_CHANGED_EVENT = "sy:llm-changed";

export default function ReasoningPicker() {
  const [state, setState] = useState<OptionsResponse | null>(null);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const wrapRef = useRef<HTMLDivElement>(null);

  const refresh = useCallback(async () => {
    try {
      const r = await fetch("/api/llm/reasoning-options");
      if (!r.ok) { setState(null); return; }
      setState((await r.json()) as OptionsResponse);
    } catch {
      setState(null);   // older daemon — control stays hidden
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  // The available efforts depend on the selected model, so re-ask
  // whenever the model changes under us.
  useEffect(() => {
    const onChanged = () => { void refresh(); };
    window.addEventListener(LLM_CHANGED_EVENT, onChanged);
    return () => window.removeEventListener(LLM_CHANGED_EVENT, onChanged);
  }, [refresh]);

  // Outside-click + Escape close (same pattern as ProviderPicker).
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") { e.stopPropagation(); setOpen(false); }
    };
    window.addEventListener("mousedown", onDown);
    window.addEventListener("keydown", onKey, true);
    return () => {
      window.removeEventListener("mousedown", onDown);
      window.removeEventListener("keydown", onKey, true);
    };
  }, [open]);

  const choose = async (effort: string | null) => {
    if (busy || !state) return;
    setBusy(true);
    try {
      const r = await fetch("/api/llm/reasoning-effort", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider: state.provider, model: state.model, effort,
        }),
      });
      if (r.ok) await refresh();
    } catch {
      /* transient — the button just doesn't change */
    } finally {
      setBusy(false);
      setOpen(false);
    }
  };

  // Nothing to choose between → no control. This is the honest signal
  // that the current model has no reasoning dial, rather than showing a
  // dead menu.
  if (!state || state.options.length === 0) return null;

  const current = state.options.find((o) => o.id === state.selected);
  const label = current ? current.label.toLowerCase() : "effort";

  return (
    <div className="sy-effort" ref={wrapRef}>
      <button
        type="button"
        className={"sy-effort-btn" + (current ? " sy-effort-btn--set" : "")}
        onClick={() => setOpen((o) => !o)}
        title={
          `Reasoning effort for ${state.model ?? state.provider}`
          + (current ? ` — ${current.label}${current.hint ? `: ${current.hint}` : ""}`
            : " — using the provider default")
        }
        aria-haspopup="menu"
        aria-expanded={open}
      >
        {label}
      </button>
      {open && (
        <div className="sy-effort-menu" role="menu">
          <div className="sy-effort-head">
            reasoning · <span>{state.model ?? state.provider}</span>
          </div>
          {state.options.map((o) => (
            <button
              key={o.id}
              type="button"
              role="menuitem"
              className={
                "sy-effort-item" + (o.id === state.selected ? " sy-effort-item--on" : "")
              }
              disabled={busy}
              onClick={() => void choose(o.id)}
            >
              <span className="sy-effort-item-label">{o.label}</span>
              {o.hint && <span className="sy-effort-item-hint">{o.hint}</span>}
            </button>
          ))}
          <button
            type="button"
            role="menuitem"
            className={
              "sy-effort-item" + (state.selected ? "" : " sy-effort-item--on")
            }
            disabled={busy}
            onClick={() => void choose(null)}
            title="Send nothing — whatever the provider does by default"
          >
            <span className="sy-effort-item-label">Auto</span>
            <span className="sy-effort-item-hint">provider default</span>
          </button>
        </div>
      )}
    </div>
  );
}
