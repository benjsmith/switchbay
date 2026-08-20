import { useEffect, useRef, useState } from "react";
import { LLM_CHANGED_EVENT } from "./ReasoningPicker";

type ProviderInfo = {
  id: string;
  label: string;
  category: string;
  default_model: string;
  /** Live model list (cached daily) — what the provider's API actually
   *  reports. Used by the picker when present; falls back to
   *  model_suggestions for offline/unsupported providers. */
  models?: string[];
  models_fresh?: boolean;
  model_suggestions?: string[];
  has_key: boolean;
  installed?: boolean;
  chosen_model?: string | null;
  /** Execution surface — set for curate-override eligibility. Only
   *  providers with BOTH can orchestrate a curation run. */
  capabilities?: { shell?: boolean; file_write?: boolean };
};

/** One path (curate / micro-edit) that runs on a different provider or
 *  model than the headline selection. */
type RoutingOverride = {
  kind: string;
  label: string;
  provider: string;
  model: string;
  provider_label: string;
  reason: string;
};

type RoutingWarning = {
  kind: string;
  scope: string;
  provider: string;
  model: string;
  message: string;
};

type Routing = {
  default: { provider: string; model: string; provider_label: string };
  overrides: RoutingOverride[];
  warnings: RoutingWarning[];
};

type ProvidersBody = {
  providers: ProviderInfo[];
  default_provider: string;
  default_model: string;
  routing?: Routing | null;
};

/** Compact pill in the rail head: shows the active provider + model
 *  and opens a dropdown to switch either. Persists via `/api/llm/default`
 *  so the choice survives reloads — every chat dispatch reads the same
 *  config. */
export default function ProviderPicker() {
  const [info, setInfo] = useState<ProvidersBody | null>(null);
  const [open, setOpen] = useState(false);
  const [runOn, setRunOn] = useState("");
  const [running, setRunning] = useState(false);
  const [runMsg, setRunMsg] = useState<string | null>(null);
  const wrapRef = useRef<HTMLDivElement>(null);

  const refresh = () =>
    fetch("/api/llm/providers")
      .then((r) => r.json())
      .then((b: ProvidersBody) => setInfo(b))
      .catch(() => setInfo(null));

  useEffect(() => {
    refresh();
  }, []);

  // Re-fetch when routing changes elsewhere — e.g. the Settings ladder
  // or micro-edit model is saved. Those panels dispatch this event so the
  // picker's routing footer + warnings don't go stale until a reload.
  useEffect(() => {
    const onChanged = () => refresh();
    window.addEventListener("sy-routing-changed", onChanged);
    // Also refresh when the tab regains focus (cheap catch-all).
    window.addEventListener("focus", onChanged);
    return () => {
      window.removeEventListener("sy-routing-changed", onChanged);
      window.removeEventListener("focus", onChanged);
    };
  }, []);

  // Close on outside click + Esc.
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (wrapRef.current && !wrapRef.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  if (!info) return null;
  const active = info.providers.find((p) => p.id === info.default_provider);
  const activeModel = info.default_model || active?.default_model || "?";
  const activeShort = shortModel(activeModel);
  const activeLabel = shortProvider(active?.label ?? info.default_provider);
  const overrides = info.routing?.overrides ?? [];
  const warnings = info.routing?.warnings ?? [];
  // Providers that can actually orchestrate a curation run (shell +
  // file-write). A propose-only provider is rejected server-side too.
  const execProviders = info.providers.filter(
    (p) => p.has_key && p.capabilities?.shell && p.capabilities?.file_write,
  );
  const runProvider = execProviders.find((p) => p.id === runOn) ?? execProviders[0];
  const runModel = (p: ProviderInfo | undefined) =>
    p ? (p.chosen_model || p.default_model || "") : "";

  const runCurate = async () => {
    if (!runProvider || running) return;
    setRunning(true);
    setRunMsg(null);
    try {
      const r = await fetch("/api/ce-action/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "curate",
          provider: runProvider.id,
          model: runModel(runProvider),
        }),
      });
      const b = await r.json();
      if (r.ok) {
        setRunMsg(`↗ curate running in background · ${b.provider_label} · ${shortModel(b.model)}`);
      } else {
        setRunMsg(b.error || `failed (HTTP ${r.status})`);
      }
    } catch (e) {
      setRunMsg((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  const choose = async (provider: string, model: string | null, force = false) => {
    const r = await fetch("/api/llm/default", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, model, force }),
    });
    if (r.ok) {
      await refresh();
      // Which reasoning efforts exist depends on the MODEL, so the
      // effort control has to re-ask after every model change.
      window.dispatchEvent(new CustomEvent(LLM_CHANGED_EVENT));
    }
    setOpen(false);
  };

  return (
    <div className="sy-rail-picker" ref={wrapRef}>
      <button
        type="button"
        className="sy-rail-pickbtn"
        onClick={() => setOpen((o) => !o)}
        title={routingTitle(active?.label ?? activeLabel, activeModel, overrides, warnings)}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label="Model picker"
      >
        <span className="sy-rail-pickbtn-text">
          {activeLabel} · <span className="sy-rail-pickmodel">{activeShort}</span>
        </span>
        {overrides.length > 0 && (
          <span
            className={
              "sy-rail-pickalt" + (warnings.length > 0 ? " sy-rail-pickalt--warn" : "")
            }
            aria-label="some tasks run on a different model"
          >
            {warnings.length > 0 ? "⚠" : "⇄"}
          </span>
        )}
        <span className="sy-rail-pickcaret">▾</span>
      </button>
      {open && (
        <div className="sy-rail-pickmenu" role="menu">
          {info.providers.filter((p) => p.has_key).length === 0 && (
            <div className="sy-rail-pickprov">
              <div className="sy-rail-pickprovhd">
                <span className="sy-rail-pickproname">No providers ready</span>
              </div>
              <div className="sy-rail-pickroutesub">
                Sign in or add a key in Settings. Unsigned CLIs stay hidden.
              </div>
            </div>
          )}
          {info.providers.filter((p) => p.has_key).map((p) => {
            // Same union as Settings (`modelsForProvider`): live list +
            // suggestions + default/chosen. Preferring only `models`
            // made Copilot's rail list diverge from Settings whenever
            // the cache was a partial live fetch.
            const union = [
              ...(p.models ?? []),
              ...(p.model_suggestions ?? []),
              p.default_model,
              p.chosen_model ?? "",
            ].map((m) => String(m || "").trim()).filter(Boolean);
            const seen = new Set<string>();
            let baseModels = union.filter((m) => (seen.has(m) ? false : (seen.add(m), true)));
            if (baseModels.length === 0) baseModels = [p.default_model];
            // BYOK providers expose dozens of models via their API — most
            // irrelevant. Show only the 6 newest/strongest (ranked by
            // version, small tiers demoted); the "paste any model id" box
            // below covers everything else.
            if (p.category === "byok") baseModels = rankModels(baseModels).slice(0, 6);
            const chosen = p.chosen_model || p.default_model;
            // If the user previously pinned a custom model that isn't
            // in the live list, surface it as the first row so they
            // can see it's still active.
            const models = chosen && !baseModels.includes(chosen)
              ? [chosen, ...baseModels]
              : baseModels;
            const isActive = p.id === info.default_provider;
            return (
              <div key={p.id} className="sy-rail-pickprov">
                <div className="sy-rail-pickprovhd">
                  <span className="sy-rail-pickproname">{p.label}</span>
                </div>
                {models.map((m) => {
                  const sel = isActive && m === chosen;
                  return (
                    <button
                      key={m}
                      type="button"
                      className={"sy-rail-pickitem" + (sel ? " sy-rail-pickitem--sel" : "")}
                      onClick={() => choose(p.id, m === p.default_model && !p.chosen_model ? null : m)}
                      disabled={!p.has_key}
                    >
                      <span className="sy-rail-pickdot">{sel ? "●" : "○"}</span>
                      {shortModel(m)}
                      <span className="sy-rail-pickfull">{m}</span>
                    </button>
                  );
                })}
                <CustomModelInput provider={p} onPick={(m) => choose(p.id, m, true)} />
              </div>
            );
          })}
          {(overrides.length > 0 || warnings.length > 0) && (
            <div className="sy-rail-pickroutes">
              <div className="sy-rail-pickrouteshd">Curation &amp; micro-edits use</div>
              <div className="sy-rail-pickroutesub">
                Rail chat uses your selection above; these tasks route to the model ladder.
              </div>
              {overrides.map((o) => (
                <div key={o.kind} className="sy-rail-pickroute" title={o.reason}>
                  <span className="sy-rail-pickroutelbl">{o.label}</span>
                  <span className="sy-rail-pickroutearrow">→</span>
                  <span className="sy-rail-pickrouteval">
                    {o.provider_label} · {shortModel(o.model)}
                  </span>
                </div>
              ))}
              {warnings.map((w, i) => (
                <div key={`w${i}`} className="sy-rail-pickwarn">
                  ⚠ {w.message}
                </div>
              ))}
            </div>
          )}
          {/* Per-run override: fire a one-off curate on a chosen
              orchestrator model in the BACKGROUND, leaving the rail on
              the picker selection. */}
          {execProviders.length > 0 && (
            <div className="sy-rail-pickcurate">
              <div className="sy-rail-pickrouteshd">Run curate in background</div>
              <div className="sy-rail-pickcuraterow">
                <select
                  className="sy-rail-pickcurate-sel"
                  value={runProvider?.id ?? ""}
                  onChange={(e) => setRunOn(e.target.value)}
                  disabled={running}
                  aria-label="curate orchestrator model"
                >
                  {execProviders.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.label} · {shortModel(runModel(p))}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="sy-rail-pickcurate-btn"
                  onClick={() => void runCurate()}
                  disabled={running || !runProvider}
                  title="Start a curate run on this model in a background thread"
                >
                  {running ? "…" : "▷ Run"}
                </button>
              </div>
              {runMsg && <div className="sy-rail-pickcurate-msg">{runMsg}</div>}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Tooltip for the picker button: names any path that runs on a
 *  different model, so the info is discoverable without opening the
 *  menu. */
function routingTitle(
  label: string,
  model: string,
  overrides: RoutingOverride[],
  warnings: RoutingWarning[],
): string {
  let t = `${label} · ${model}`;
  for (const o of overrides) {
    t += `\n${o.label} → ${o.provider_label} · ${o.model}`;
  }
  if (warnings.length > 0) t += `\n⚠ ${warnings.length} risk warning(s)`;
  return t;
}

/** Escape hatch: type any model id (e.g. "gpt-5.5-preview", a
 *  brand-new model the live list doesn't have yet, or a fine-tune).
 *  Submitted via Enter; on success the parent picker re-renders with
 *  the new chosen_model. */
function CustomModelInput({
  provider,
  onPick,
}: {
  provider: ProviderInfo;
  onPick: (model: string) => void;
}) {
  const [val, setVal] = useState("");
  const submit = () => {
    const trimmed = val.trim();
    if (trimmed) {
      onPick(trimmed);
      setVal("");
    }
  };
  return (
    <form
      className="sy-rail-pickcustom"
      onSubmit={(e) => { e.preventDefault(); submit(); }}
    >
      <input
        type="text"
        className="sy-rail-pickcustom-input"
        placeholder="paste any model id…"
        value={val}
        onChange={(e) => setVal(e.target.value)}
        disabled={!provider.has_key}
      />
      <button
        type="submit"
        className="sy-rail-pickcustom-btn"
        disabled={!provider.has_key || !val.trim()}
      >
        set
      </button>
    </form>
  );
}

/** Rank BYOK model ids newest/strongest first, so the picker can show
 *  just the top few. Primary key: the version number embedded in the id
 *  (`claude-sonnet-5` → 5.0, `claude-opus-4-8` → 4.8, `gpt-5.6` → 5.6,
 *  `gemini-2.5-flash` → 2.5) — higher = newer, so a gen-5 model sorts
 *  above Opus 4.8. Tiebreak: small/fast tiers (mini/nano/haiku/flash/…)
 *  sink below flagships at the same version. Stable otherwise. */
function rankModels(ids: string[]): string[] {
  const score = (id: string): [number, number] => {
    const s = id.toLowerCase();
    const m = s.match(/(\d+)(?:[.\-](\d+))?/);
    let ver = 0;
    if (m) ver = parseInt(m[1], 10) + (m[2] ? parseInt(m[2], 10) / (m[2].length > 1 ? 100 : 10) : 0);
    const small = /(mini|nano|tiny|lite|fast|haiku|flash|small|composer|\b\d+b\b)/.test(s) ? 0 : 1;
    return [ver, small];
  };
  return ids
    .map((id, i) => ({ id, i, k: score(id) }))
    .sort((a, b) => (b.k[0] - a.k[0]) || (b.k[1] - a.k[1]) || (a.i - b.i))
    .map((x) => x.id);
}

/** Rail-head label: keep the pill one line. Full name stays in the title. */
function shortProvider(label: string): string {
  if (/^MLX\b/i.test(label)) return "MLX";
  if (/^llama\.cpp/i.test(label)) return "llama.cpp";
  return label;
}

/** Compact display: drop the vendor prefix and version-y suffix where
 *  redundant. e.g. `claude-sonnet-4-6` → `sonnet 4.6`. Falls back to
 *  the raw id for unknown shapes. */
function shortModel(id: string): string {
  // Claude Code aliases resolve to the latest model of each tier.
  if (/^(opus|sonnet|haiku|default)$/i.test(id)) return `${id.toLowerCase()} (latest)`;
  const m = id.match(/^claude-(opus|sonnet|haiku)-(\d+)-(\d+)/i);
  if (m) return `${m[1]} ${m[2]}.${m[3]}`;
  let s = id.trim();
  const slash = s.lastIndexOf("/");
  if (slash >= 0) s = s.slice(slash + 1);
  s = s.replace(/^mlx:/i, "");
  s = s.replace(/^(?:mlx-community|huggingface|lmstudio|mlx)[_-]+/i, "");
  return s || id;
}
