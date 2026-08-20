import React, { useEffect, useRef, useState } from "react";

type ProviderInfo = {
  auth_flow?: string;
  id: string;
  label: string;
  category: string;
  default_model: string;
  /** Live / cached model ids from the daemon model_cache. */
  models?: string[];
  model_suggestions?: string[];
  models_fresh?: boolean;
  chosen_model?: string | null;
  key_placeholder?: string;
  key_help_url?: string;
  has_key: boolean;
  installed?: boolean;
  capabilities: { chat: boolean; streaming: boolean; tools: boolean };
  binary?: string;
  auth_help?: string;
};

/** Models available for a ladder rung's provider select. */
function modelsForProvider(p: ProviderInfo | undefined): string[] {
  if (!p) return [];
  const raw = [
    ...(p.models ?? []),
    ...(p.model_suggestions ?? []),
    p.default_model,
    p.chosen_model ?? "",
  ].map((m) => String(m || "").trim()).filter(Boolean);
  const seen = new Set<string>();
  const out: string[] = [];
  for (const m of raw) {
    if (seen.has(m)) continue;
    seen.add(m);
    out.push(m);
  }
  return out;
}

type PolicyView = {
  profile: string;
  source: string | null;
  features: Record<string, boolean>;
};

type ProvidersBody = {
  providers: ProviderInfo[];
  keychain_available: boolean;
  keychain_backend: string;
  default_provider: string;
  default_model?: string;
  policy?: PolicyView;
};

type Props = {
  open: boolean;
  onClose: () => void;
  /** Stop the whole daemon (Settings → Quit). App owns the overlay +
   *  socket teardown; we own only the confirm. */
  onQuit: () => void;
  /** Restart the daemon (Settings → Restart = `make restart`). App owns
   *  the POST + toast; we own the confirm. */
  onRestart: () => void;
  /** Check GitHub + apply older Switch Bay / CE / merge releases, then
   *  restart. App owns the POST + toast; we own the confirm. */
  onUpdate: () => void;
};

export default function SettingsModal({ open, onClose, onQuit, onRestart, onUpdate }: Props) {
  const [info, setInfo] = useState<ProvidersBody | null>(null);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<Record<string, { ok: boolean; msg: string } | null>>({});

  useEffect(() => {
    if (!open) return;
    // Don't close on Escape while editing ladder/model fields or while
    // a native <select> is open — that was wiping in-progress ladder edits.
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      const t = e.target as HTMLElement | null;
      if (t?.closest?.("input, textarea, select, [contenteditable='true']")) {
        return;
      }
      onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  useEffect(() => {
    if (!open) return;
    fetch("/api/llm/providers")
      .then((r) => r.json())
      .then((b: ProvidersBody) => setInfo(b))
      .catch(() => { /* keychain endpoint missing on older daemons */ });
  }, [open]);

  if (!open) return null;

  const refresh = async () => {
    const r = await fetch("/api/llm/providers");
    if (r.ok) setInfo((await r.json()) as ProvidersBody);
  };

  const saveKey = async (id: string) => {
    const key = (drafts[id] ?? "").trim();
    if (!key) return;
    setBusy(`save:${id}`);
    setStatus((s) => ({ ...s, [id]: null }));
    try {
      const r = await fetch("/api/llm/key", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: id, key }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setStatus((s) => ({ ...s, [id]: { ok: false, msg: body.error ?? `HTTP ${r.status}` } }));
        return;
      }
      setDrafts((d) => ({ ...d, [id]: "" }));
      await refresh();
      setStatus((s) => ({ ...s, [id]: { ok: true, msg: "saved to keychain" } }));
    } finally {
      setBusy(null);
    }
  };

  const testKey = async (id: string) => {
    setBusy(`test:${id}`);
    setStatus((s) => ({ ...s, [id]: null }));
    try {
      const r = await fetch("/api/llm/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: id }),
      });
      const body = await r.json().catch(() => ({}));
      if (r.ok) {
        setStatus((s) => ({ ...s, [id]: { ok: true, msg: "ping ok" } }));
      } else {
        setStatus((s) => ({
          ...s,
          [id]: { ok: false, msg: `${body.code ?? "error"}: ${body.message ?? "failed"}` },
        }));
      }
    } finally {
      setBusy(null);
    }
  };

  const removeKey = async (id: string) => {
    setBusy(`del:${id}`);
    try {
      await fetch("/api/llm/key", {
        method: "DELETE",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: id }),
      });
      await refresh();
      setStatus((s) => ({ ...s, [id]: { ok: true, msg: "removed" } }));
    } finally {
      setBusy(null);
    }
  };

  const makeDefault = async (id: string) => {
    setBusy(`def:${id}`);
    setStatus((s) => ({ ...s, [id]: null }));
    try {
      const r = await fetch("/api/llm/default", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider: id }),
      });
      const body = await r.json().catch(() => ({}));
      if (!r.ok) {
        setStatus((s) => ({ ...s, [id]: { ok: false, msg: body.error ?? `HTTP ${r.status}` } }));
        return;
      }
      await refresh();
      setStatus((s) => ({ ...s, [id]: { ok: true, msg: "now default for chat" } }));
    } finally {
      setBusy(null);
    }
  };

  return (
    <div
      className="sy-confirm-backdrop"
      // Close only when the press lands on the dimmed area itself.
      // Do NOT stopPropagation on the dialog mousedown — that made
      // native <select> menus flash open then immediately collapse
      // (first click open failed; second click worked).
      onMouseDown={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div
        className="sy-confirm sy-settings"
        role="dialog"
        aria-labelledby="sy-settings-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div id="sy-settings-title" className="sy-confirm-title">Settings · LLM providers</div>
        <div className="sy-confirm-body sy-settings-body">
          {!info && <p>Loading…</p>}
          {info && !info.keychain_available && (
            <p style={{ color: "var(--type-fact)" }}>
              OS keychain unavailable ({info.keychain_backend}). API keys cannot be persisted on
              this machine. Set <code>ANTHROPIC_API_KEY</code> in the daemon's environment as a
              workaround.
            </p>
          )}
          {info && info.keychain_available && (
            <p className="sy-settings-keychain">
              Keys stored in: <code>{info.keychain_backend}</code>. Plaintext is never written
              to disk.
            </p>
          )}
          {info?.policy?.profile === "enterprise" && (
            <p className="sy-settings-keychain">
              Managed by your organisation. Provider list and some
              Settings panels are locked by admin policy
              {info.policy.source ? <> (<code>{info.policy.source}</code>)</> : null}.
            </p>
          )}
          {/* Local backends (llama.cpp / MLX / Ollama) live only in the
              Local agent model section below — hide their provider cards
              here so cloud vs local isn't duplicated/confusing. They
              remain available in the model ladder provider dropdown. */}
          {info?.providers
            .filter((p) => p.id !== "ollama" && p.id !== "llamacpp" && p.id !== "mlx")
            .map((p) => {
            const s = status[p.id];
            const isDefault = info.default_provider === p.id;
            const isSubscription = p.category === "subscription";
            // Anything that doesn't take a user-typed API key (subscription
            // CLIs) shares the "no key field" UI: status badge + Test +
            // Make-default.
            const isKeyless = p.category !== "byok";
            return (
              <React.Fragment key={p.id}>
              <div className="sy-settings-provider">
                <div className="sy-settings-provider-head">
                  <span className="sy-settings-provider-label">{p.label}</span>
                  <span className="sy-settings-provider-meta">
                    {p.category}
                    {` · ${p.default_model}`}
                  </span>
                  {isDefault && (
                    <span className="sy-settings-badge sy-settings-badge--default">
                      default
                    </span>
                  )}
                  {p.has_key ? (
                    <span className="sy-settings-badge sy-settings-badge--ok">
                      {isKeyless ? "available" : "key set"}
                    </span>
                  ) : (
                    <span className="sy-settings-badge">
                      {isKeyless
                        ? (p.installed ? "not signed in" : "not installed")
                        : "no key"}
                    </span>
                  )}
                </div>
                {isKeyless ? (
                  p.auth_flow === "github_device" ? (
                    /* Full-width stack: device-flow UI must not share a
                     * horizontal flex row with long auth_help (that
                     * collapses help to one char/line). */
                    <div className="sy-settings-keyless-stack">
                      <CopilotAuth authed={p.has_key} onChanged={() => void refresh()} />
                      <div className="sy-settings-keyless-footer">
                        <p className="sy-settings-help">
                          {p.has_key
                            ? "Signed in — subscription auth is reused; no API key stored."
                            : "Browser sign-in. Needs an active Copilot subscription. Personal accounts: Sign in. Enterprise / EMU: Enterprise… first."}
                        </p>
                        <button
                          type="button"
                          className="sy-confirm-btn"
                          onClick={() => testKey(p.id)}
                          disabled={busy !== null || !p.has_key}
                        >
                          {busy === `test:${p.id}` ? "Testing…" : "Test"}
                        </button>
                        {p.has_key && !isDefault && (
                          <button
                            type="button"
                            className="sy-confirm-btn"
                            onClick={() => makeDefault(p.id)}
                            disabled={busy !== null}
                          >
                            Make default
                          </button>
                        )}
                      </div>
                    </div>
                  ) : (
                  <div className="sy-settings-row">
                    <span className="sy-settings-help" style={{ flex: 1, margin: 0 }}>
                      {linkify(
                        p.has_key
                          ? (isSubscription
                              ? `Using ${p.binary ?? "the CLI"} subprocess — your subscription auth is reused, no API key stored.`
                              : (p.auth_help ?? "Local provider — no API key needed."))
                          : (p.auth_help ?? `Install the ${p.binary ?? "provider"} to enable.`),
                      )}
                    </span>
                    <button
                      type="button"
                      className="sy-confirm-btn"
                      onClick={() => testKey(p.id)}
                      disabled={busy !== null || !p.has_key}
                    >
                      {busy === `test:${p.id}` ? "Testing…" : "Test"}
                    </button>
                    {p.has_key && !isDefault && (
                      <button
                        type="button"
                        className="sy-confirm-btn"
                        onClick={() => makeDefault(p.id)}
                        disabled={busy !== null}
                      >
                        Make default
                      </button>
                    )}
                  </div>
                  )
                ) : (
                  <div className="sy-settings-row">
                    <input
                      type="password"
                      className="sy-ws-input"
                      placeholder={p.key_placeholder ?? "API key"}
                      value={drafts[p.id] ?? ""}
                      onChange={(e) => setDrafts((d) => ({ ...d, [p.id]: e.target.value }))}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" && drafts[p.id]) saveKey(p.id);
                      }}
                      style={{ flex: 1, marginTop: 0 }}
                      spellCheck={false}
                    />
                    <button
                      type="button"
                      className="sy-confirm-btn sy-confirm-btn--primary"
                      onClick={() => saveKey(p.id)}
                      disabled={busy !== null || !(drafts[p.id] ?? "").trim()}
                    >
                      {busy === `save:${p.id}` ? "Saving…" : "Save"}
                    </button>
                    <button
                      type="button"
                      className="sy-confirm-btn"
                      onClick={() => testKey(p.id)}
                      disabled={busy !== null || !p.has_key}
                    >
                      {busy === `test:${p.id}` ? "Testing…" : "Test"}
                    </button>
                    <button
                      type="button"
                      className="sy-confirm-btn"
                      onClick={() => removeKey(p.id)}
                      disabled={busy !== null || !p.has_key}
                    >
                      Remove
                    </button>
                    {p.has_key && !isDefault && (
                      <button
                        type="button"
                        className="sy-confirm-btn"
                        onClick={() => makeDefault(p.id)}
                        disabled={busy !== null}
                      >
                        Make default
                      </button>
                    )}
                  </div>
                )}
                {p.key_help_url && !isKeyless && (
                  <p className="sy-settings-help">
                    Get a key at{" "}
                    <a href={p.key_help_url} target="_blank" rel="noreferrer">
                      {p.key_help_url}
                    </a>
                  </p>
                )}
                {s && (
                  <p className={"sy-settings-status" + (s.ok ? "" : " sy-settings-status--err")}>
                    {s.msg}
                  </p>
                )}
              </div>
              </React.Fragment>
            );
          })}
          <LocalModelPanel
            open={open}
            onClose={onClose}
            hfDownloads={info?.policy?.features?.hf_model_download ?? true}
          />
          <LadderPanel open={open} providers={info?.providers ?? []} />
          <PacksPanel open={open} />
          {(info?.policy?.features?.user_mcp_servers ?? true) && (
            <McpServersPanel open={open} />
          )}
          <UserTabsPanel open={open} />
          <PermissionsPanel open={open} />
          <StoragePanel open={open} />
          {(info?.policy?.features?.media_generation ?? true) && (
            <MediaPanel open={open} />
          )}
          <WorkspacesHomePanel open={open} />
          <CuratorPanel open={open} />
          {(info?.policy?.features?.watch_folders ?? true) && (
            <WatchFoldersPanel open={open} />
          )}
          {(info?.policy?.features?.comms_streams ?? true) && (
            <StreamsPanel open={open} />
          )}
          <HistoryPanel open={open} />
          <ThrustersEgg open={open} onClose={onClose} />
        </div>
        <div className="sy-confirm-actions sy-settings-footer">
          <div className="sy-settings-power">
            {(info?.policy?.features?.in_app_update ?? true) && (
            <button
              type="button"
              className="sy-confirm-btn sy-settings-update"
              title="Check GitHub for later releases of Switch Bay, Curiosity Engine, and Curiosity Merge"
              onClick={() => {
                const ok = window.confirm(
                  "Update Switch Bay?\n\n"
                  + "This checks GitHub for later releases of Switch Bay, "
                  + "Curiosity Engine, and Curiosity Merge, and updates "
                  + "anything that's behind. Switch Bay then restarts so "
                  + "the app picks up the changes.\n\n"
                  + "Agents that are still running will end. Nothing "
                  + "you've saved is lost.",
                );
                if (!ok) return;
                onClose();
                onUpdate();
              }}
            >
              ↓ Update
            </button>
            )}
            <button
              type="button"
              className="sy-confirm-btn sy-settings-restart"
              title="Restart the Switch Bay daemon (make restart)"
              onClick={() => {
                const ok = window.confirm(
                  "Restart Switch Bay?\n\n"
                  + "This restarts the background daemon and ends any agents "
                  + "that are still running. Nothing you've saved is lost — "
                  + "the app reconnects on its own once it's back up.",
                );
                if (!ok) return;
                onClose();
                onRestart();
              }}
            >
              ↻ Restart
            </button>
            <button
              type="button"
              className="sy-confirm-btn sy-settings-quit"
              title="Stop the Switch Bay daemon for all workspaces"
              onClick={() => {
                const ok = window.confirm(
                  "Stop Switch Bay?\n\n"
                  + "This stops the background daemon for ALL workspaces and "
                  + "ends any agents that are still running. Nothing you've "
                  + "saved is lost.\n\n"
                  + 'Restart later with "make restart", or it starts again '
                  + "the next time you log in.",
                );
                if (!ok) return;
                onClose();
                onQuit();
              }}
            >
              ⏻ Quit Switch Bay…
            </button>
          </div>
          <button type="button" className="sy-confirm-btn" onClick={onClose}>Close</button>
        </div>
      </div>
    </div>
  );
}


// ── Model ladder panel ──────────────────────────────────────────────


type Rung = { provider: string; model: string; effort?: string };
type LadderState = Partial<Record<"trivial" | "normal" | "hard", Rung>>;

type Picker = { provider: string; provider_label: string; model: string };

// CE-curation ladder roles (2026-07-24). The ladder is no longer a
// global override — it configures CE actions (curate/ingest) only.
const RUNG_ROLE: Record<"hard" | "normal" | "trivial", { title: string; note: string }> = {
  hard: { title: "Orchestrator", note: "the top-level curate agent" },
  normal: { title: "Workers", note: "CE fan-out workers" },
  trivial: { title: "Sub-tasks", note: "cheap CE sub-calls" },
};

function LadderPanel(props: { open: boolean; providers: ProviderInfo[] }) {
  // Two scopes (2026-07-05 ruling): GLOBAL defaults apply everywhere;
  // a workspace can override individual rungs (e.g. a software
  // workspace pins `hard` to a stronger model while a literature
  // workspace keeps the defaults).
  const [glob, setGlob] = useState<LadderState | null>(null);
  const [wsLadder, setWsLadder] = useState<LadderState>({});
  const [wsName, setWsName] = useState("");
  const [picker, setPicker] = useState<Picker | null>(null);
  const [scope, setScope] = useState<"global" | "workspace">("global");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  // Orchestrator (hard) first — the CE role hierarchy reads top-down.
  const difficulties: ("hard" | "normal" | "trivial")[] = ["hard", "normal", "trivial"];

  useEffect(() => {
    if (!props.open) return;
    void (async () => {
      try {
        const r = await fetch("/api/llm/ladder");
        if (!r.ok) return;
        const body = (await r.json()) as {
          global?: LadderState; workspace?: LadderState;
          ladder?: LadderState; workspace_name?: string; picker?: Picker;
        };
        setGlob(body.global ?? body.ladder ?? {});
        setWsLadder(body.workspace ?? {});
        setWsName(body.workspace_name ?? "");
        setPicker(body.picker ?? null);
      } catch { /* leave null — empty state shows */ }
    })();
  }, [props.open]);

  const ladder = scope === "global" ? glob : wsLadder;
  const setLadder = scope === "global" ? setGlob : setWsLadder;

  const update = (diff: typeof difficulties[number], next: Partial<Rung>) => {
    setLadder((cur: LadderState | null) => {
      const prev = cur?.[diff] ?? { provider: "", model: "" };
      const merged: Rung = { ...prev, ...next };
      // Switching provider: pick that provider's first available model
      // so the model dropdown is never stuck on another family's id.
      if (next.provider !== undefined && next.provider !== prev.provider) {
        if (!next.provider.trim()) {
          merged.model = "";
          merged.effort = "";
        } else if (next.model === undefined) {
          const p = props.providers.find((x) => x.id === next.provider);
          const opts = modelsForProvider(p);
          merged.model = opts[0] ?? p?.default_model ?? "";
          merged.effort = "";
        }
      }
      if (next.model !== undefined && next.model !== prev.model && next.effort === undefined) {
        merged.effort = "";
      }
      const out = { ...(cur ?? {}) };
      // Drop rungs the user blanks out so the saved JSON stays clean
      // (in workspace scope, a blank rung = "use the global default").
      if (!merged.provider.trim() && !merged.model.trim()) {
        delete out[diff];
      } else {
        out[diff] = merged;
      }
      return out;
    });
    setStatus(null);
  };

  const save = async () => {
    if (!ladder || busy) return;
    setBusy(true);
    setStatus(null);
    try {
      const r = await fetch("/api/llm/ladder", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scope, ladder }),
      });
      if (!r.ok) {
        const body = await r.json();
        setStatus({ ok: false, msg: body.error || `HTTP ${r.status}` });
        return;
      }
      const body = (await r.json()) as {
        global?: LadderState; workspace?: LadderState; ladder?: LadderState;
      };
      setGlob(body.global ?? body.ladder ?? {});
      setWsLadder(body.workspace ?? {});
      // Nudge the rail model picker to re-fetch its routing footer/warnings.
      window.dispatchEvent(new CustomEvent("sy-routing-changed"));
      setStatus({ ok: true, msg: scope === "global" ? "saved — applies to every workspace without overrides" : `saved — overrides for ${wsName}` });
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="sy-settings-ladder">
      <h3 className="sy-settings-h3">CE curation models</h3>
      <p className="sy-settings-blurb">
        Curate / ingest only — rail chat stays on the picker. Override a
        rung to pin a model; a cheaper rung can be a smaller model or a
        lower effort on the same one.
      </p>
      <div className="sy-side-seg" role="tablist" aria-label="Ladder scope" style={{ marginBottom: 8 }}>
        <button
          type="button"
          role="tab"
          aria-selected={scope === "global"}
          className={"sy-side-seg-btn" + (scope === "global" ? " sy-side-seg-btn--on" : "")}
          onClick={() => setScope("global")}
          title="Defaults that apply in every workspace"
        >
          Global defaults
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={scope === "workspace"}
          className={"sy-side-seg-btn" + (scope === "workspace" ? " sy-side-seg-btn--on" : "")}
          onClick={() => setScope("workspace")}
          title="Per-rung overrides for the active workspace — blank rungs inherit the global default"
        >
          {wsName || "This workspace"}
        </button>
      </div>
      <div className="sy-settings-ladder-rows">
        {difficulties.map((diff) => {
          const rung = ladder?.[diff];
          const globRung = glob?.[diff];
          const role = RUNG_ROLE[diff];
          const pid = rung?.provider ?? "";
          const provider = props.providers.find((p) => p.id === pid);
          const modelOpts = modelsForProvider(provider);
          // Keep a saved/legacy model id visible even if not in live list.
          const modelValue = rung?.model ?? "";
          const modelChoices = modelValue && !modelOpts.includes(modelValue)
            ? [modelValue, ...modelOpts]
            : modelOpts;
          const isSet = !!pid;
          // "Follows picker" when this rung is unset AND (for the
          // orchestrator) no global pin covers it. The orchestrator's
          // unset default is the picker; workers/sub-tasks unset also
          // fall through to the picker.
          const followsPicker = !isSet && !(scope === "workspace" && globRung);
          const globLabel = scope === "workspace" && globRung
            ? `global: ${globRung.provider} / ${globRung.model}`
            : null;
          return (
            <div key={diff} className="sy-settings-ladder-row">
              <span className="sy-settings-ladder-label" title={role.note}>
                <strong>{role.title}</strong>
                <span className="sy-settings-ladder-diff">{diff}</span>
              </span>
              {followsPicker ? (
                <div className="sy-settings-ladder-follow">
                  <span className="sy-settings-ladder-followtxt" title="Runs on your rail picker selection">
                    Follows picker{picker ? `: ${picker.provider_label} · ${picker.model}` : ""}
                  </span>
                  <button
                    type="button"
                    className="sy-settings-mini-btn"
                    onClick={() => update(diff, {
                      provider: picker?.provider || props.providers[0]?.id || "",
                      model: picker?.model || "",
                    })}
                  >
                    Override…
                  </button>
                </div>
              ) : (
                <>
                  <select
                    className="sy-settings-input"
                    value={pid}
                    onChange={(e) => update(diff, { provider: e.target.value })}
                    aria-label={`${diff} provider`}
                  >
                    <option value="">{globLabel ? `(use ${globLabel})` : "(follows picker)"}</option>
                    {props.providers.map((p) => (
                      <option key={p.id} value={p.id}>{p.label}</option>
                    ))}
                  </select>
                  <select
                    className="sy-settings-input"
                    value={modelValue}
                    disabled={!pid}
                    onChange={(e) => update(diff, { model: e.target.value })}
                    aria-label={`${diff} model`}
                  >
                    {!pid && <option value="">(pick provider first)</option>}
                    {pid && modelChoices.length === 0 && (
                      <option value="">(no models — install or refresh)</option>
                    )}
                    {pid && modelChoices.map((m) => (
                      <option key={m} value={m}>{m}</option>
                    ))}
                  </select>
                  <RungEffortSelect
                    provider={pid}
                    model={modelValue}
                    value={rung?.effort ?? ""}
                    onChange={(effort) => update(diff, { effort })}
                  />
                  <button
                    type="button"
                    className="sy-settings-mini-btn"
                    title="Clear this rung → follow the picker"
                    onClick={() => update(diff, { provider: "", model: "", effort: "" })}
                  >
                    ✕
                  </button>
                </>
              )}
            </div>
          );
        })}
      </div>
      <div className="sy-settings-ladder-actions">
        <button
          type="button"
          className="sy-confirm-btn"
          disabled={busy || ladder === null}
          onClick={() => void save()}
        >
          {busy ? "Saving…" : "Save ladder"}
        </button>
        {status && (
          <span
            className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}
          >
            {status.msg}
          </span>
        )}
      </div>
      {picker && (
        <div className="sy-settings-ladder-row sy-settings-ladder-row--effort">
          <span className="sy-settings-ladder-label">
            <strong>Rail effort</strong>
          </span>
          <EffortSelect
            provider={picker.provider}
            model={picker.model}
            label={`${picker.provider_label} · ${picker.model}`}
          />
        </div>
      )}
      <MicroEditModelPanel open={props.open} providers={props.providers} picker={picker} />
    </section>
  );
}


// ── Reasoning effort ────────────────────────────────────────────────
// The third picker dimension. Options are fetched PER provider+model
// from the daemon — a provider's reasoning models and its plain ones
// take different values, and several take none — so this renders
// nothing rather than a dead control when the pair has no dial.
// Mirrors the rail's corner control; same endpoints, same storage.

type EffortOption = { id: string; label: string; hint?: string };

/** Per-rung effort. Saved on the ladder row (not the global
 *  provider+model store) so two rungs can share grok-4.6 and still
 *  think at different depths. */
function RungEffortSelect({
  provider, model, value, onChange,
}: {
  provider: string; model: string; value: string;
  onChange: (effort: string) => void;
}) {
  const [options, setOptions] = useState<EffortOption[]>([]);
  useEffect(() => {
    let cancelled = false;
    if (!provider) { setOptions([]); return; }
    void (async () => {
      try {
        const qs = new URLSearchParams({ provider, model: model || "" });
        const r = await fetch(`/api/llm/reasoning-options?${qs}`);
        if (!r.ok) { if (!cancelled) setOptions([]); return; }
        const b = (await r.json()) as { options?: EffortOption[] };
        if (!cancelled) setOptions(b.options ?? []);
      } catch {
        if (!cancelled) setOptions([]);
      }
    })();
    return () => { cancelled = true; };
  }, [provider, model]);

  if (!provider || options.length === 0) {
    return <span className="sy-settings-effort-placeholder" aria-hidden="true" />;
  }
  const known = options.some((o) => o.id === value);
  return (
    <select
      className="sy-settings-input"
      value={known ? value : ""}
      onChange={(e) => onChange(e.target.value)}
      aria-label="reasoning effort"
      title="How hard this rung thinks. Same model + lower effort is a cheaper rung."
    >
      <option value="">(inherit)</option>
      {options.map((o) => (
        <option key={o.id} value={o.id}>
          {o.label}{o.hint ? ` — ${o.hint}` : ""}
        </option>
      ))}
    </select>
  );
}

function EffortSelect({
  provider, model, label = "Reasoning",
}: {
  provider: string; model: string; label?: string;
}) {
  const [options, setOptions] = useState<EffortOption[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    if (!provider) { setOptions([]); return; }
    void (async () => {
      try {
        const qs = new URLSearchParams({ provider, model: model || "" });
        const r = await fetch(`/api/llm/reasoning-options?${qs}`);
        if (!r.ok) { if (!cancelled) setOptions([]); return; }
        const b = (await r.json()) as { options?: EffortOption[]; selected?: string | null };
        if (cancelled) return;
        setOptions(b.options ?? []);
        setSelected(b.selected ?? "");
      } catch {
        if (!cancelled) setOptions([]);
      }
    })();
    return () => { cancelled = true; };
  }, [provider, model]);

  const choose = async (effort: string) => {
    setBusy(true);
    try {
      await fetch("/api/llm/reasoning-effort", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ provider, model, effort: effort || null }),
      });
      setSelected(effort);
      window.dispatchEvent(new CustomEvent("sy:llm-changed"));
    } catch { /* transient */ } finally { setBusy(false); }
  };

  if (options.length === 0) return null;
  return (
    <label
      className="sy-effort-select"
      title="How hard this model thinks. Higher costs more and is slower."
    >
      <span className="sy-effort-select-meta" title={label}>{label}</span>
      <select
        className="sy-settings-input sy-effort-select-input"
        value={selected}
        disabled={busy}
        onChange={(e) => void choose(e.target.value)}
      >
        <option value="">(provider default)</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>
            {o.label}{o.hint ? ` — ${o.hint}` : ""}
          </option>
        ))}
      </select>
    </label>
  );
}


// ── Micro-edit fast-model ───────────────────────────────────────────
// Decoupled from the CE ladder (2026-07-24): a single optional fast
// model for tiny, edit-shaped rail messages (cell formulas, slide copy,
// SQL, plot tweaks with a live tab focused). Unset → follows the picker.

function MicroEditModelPanel(props: {
  open: boolean; providers: ProviderInfo[]; picker: Picker | null;
}) {
  const [pid, setPid] = useState("");
  const [model, setModel] = useState("");
  const [effort, setEffort] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);

  const load = () => {
    void (async () => {
      try {
        const r = await fetch("/api/micro-edits/model");
        if (!r.ok) return;
        const b = (await r.json()) as {
          global?: { provider?: string | null; model?: string | null; effort?: string | null };
        };
        setPid(b.global?.provider ?? "");
        setModel(b.global?.model ?? "");
        setEffort(b.global?.effort ?? "");
      } catch { /* leave empty */ }
    })();
  };
  useEffect(() => { if (props.open) load(); }, [props.open]);

  const provider = props.providers.find((p) => p.id === pid);
  const modelOpts = modelsForProvider(provider);
  const modelChoices = model && !modelOpts.includes(model) ? [model, ...modelOpts] : modelOpts;

  const save = async (clear = false) => {
    setBusy(true); setMsg(null);
    try {
      const body = clear ? { provider: "" } : { provider: pid, model, effort };
      const r = await fetch("/api/micro-edits/model", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!r.ok) { setMsg("save failed"); return; }
      const b = (await r.json()) as {
        global?: { provider?: string | null; model?: string | null; effort?: string | null };
      };
      setPid(b.global?.provider ?? "");
      setModel(b.global?.model ?? "");
      setEffort(b.global?.effort ?? "");
      window.dispatchEvent(new CustomEvent("sy-routing-changed"));
      setMsg(clear ? "cleared — micro-edits follow the picker" : "saved");
    } finally { setBusy(false); }
  };

  const follows = !pid;
  return (
    <div className="sy-settings-microedit">
      <h4 className="sy-settings-h4">Micro-edits fast model</h4>
      <p className="sy-settings-blurb">
        Tiny edit-shaped messages (a cell formula, a slide caption) can
        run on a cheaper model or a lower effort.{" "}
        {follows
          ? <>Currently <strong>follows the picker</strong>{props.picker ? ` (${props.picker.provider_label} · ${props.picker.model})` : ""}.</>
          : <>Currently <strong>{pid} · {model || "(default)"}</strong>{effort ? ` · ${effort}` : ""}.</>}
      </p>
      <div className="sy-settings-ladder-row">
        <span className="sy-settings-ladder-label"><strong>Fast model</strong></span>
        <select
          className="sy-settings-input" value={pid}
          onChange={(e) => { setPid(e.target.value); setModel(""); setEffort(""); }}
          aria-label="micro-edit provider"
        >
          <option value="">(follows picker)</option>
          {props.providers.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
        <select
          className="sy-settings-input" value={model} disabled={!pid}
          onChange={(e) => { setModel(e.target.value); setEffort(""); }}
          aria-label="micro-edit model"
        >
          {!pid && <option value="">(pick provider first)</option>}
          {pid && modelChoices.length === 0 && <option value="">(no models)</option>}
          {pid && modelChoices.map((m) => <option key={m} value={m}>{m}</option>)}
        </select>
        <RungEffortSelect
          provider={pid}
          model={model}
          value={effort}
          onChange={setEffort}
        />
      </div>
      <div className="sy-settings-ladder-actions">
        <button type="button" className="sy-confirm-btn" disabled={busy || !pid}
          onClick={() => void save(false)}>
          {busy ? "Saving…" : "Save fast model"}
        </button>
        {!follows && (
          <button type="button" className="sy-settings-mini-btn" disabled={busy}
            onClick={() => void save(true)}>
            Clear (follow picker)
          </button>
        )}
        {msg && <span className="sy-settings-status">{msg}</span>}
      </div>
    </div>
  );
}


// ── MCP servers panel ───────────────────────────────────────────────
// User-registered MCP servers (bring-your-own tools), fanned into every
// agent CLI we spawn. Verified at add time (a real MCP handshake) with
// rollback — a broken server never persists. Mirrors the streams add-
// form pattern. Nothing is ever fetched from a catalog.

type McpServer = {
  name: string; transport: "stdio" | "http"; enabled: boolean;
  command?: string; args?: string[]; env?: Record<string, string>;
  url?: string; headers?: Record<string, string>;
};

function parseKV(text: string): Record<string, string> {
  const out: Record<string, string> = {};
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t) continue;
    const eq = t.indexOf("=");
    if (eq > 0) out[t.slice(0, eq).trim()] = t.slice(eq + 1).trim();
  }
  return out;
}

function McpServersPanel({ open }: { open: boolean }) {
  const [servers, setServers] = useState<McpServer[] | null>(null);
  const [transport, setTransport] = useState<"stdio" | "http">("stdio");
  const [name, setName] = useState("");
  const [command, setCommand] = useState("");
  const [argsText, setArgsText] = useState("");
  const [url, setUrl] = useState("");
  const [envText, setEnvText] = useState("");
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const refresh = () =>
    fetch("/api/mcp-servers").then((r) => r.json())
      .then((b) => setServers(b.servers as McpServer[])).catch(() => setServers([]));
  useEffect(() => { if (open) refresh(); }, [open]);

  const add = async () => {
    setBusy(true); setMsg(null);
    try {
      const payload: McpServer = transport === "stdio"
        ? { name, transport, enabled: true, command,
            args: argsText.split(/\s+/).filter(Boolean), env: parseKV(envText) }
        : { name, transport, enabled: true, url, headers: parseKV(envText) };
      const r = await fetch("/api/mcp-servers/add", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const b = await r.json();
      if (!r.ok) { setMsg({ ok: false, text: b.error || `HTTP ${r.status}` }); return; }
      setMsg({ ok: true, text: `added "${name}" — verified` });
      setName(""); setCommand(""); setArgsText(""); setUrl(""); setEnvText("");
      setServers(b.servers as McpServer[]);
    } finally { setBusy(false); }
  };

  const toggle = async (s: McpServer) => {
    const r = await fetch("/api/mcp-servers/toggle", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: s.name, enabled: !s.enabled }),
    });
    const b = await r.json();
    if (r.ok) setServers(b.servers as McpServer[]);
  };
  const del = async (s: McpServer) => {
    if (!window.confirm(`Remove MCP server "${s.name}"?`)) return;
    const r = await fetch("/api/mcp-servers/delete", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: s.name }),
    });
    const b = await r.json();
    if (r.ok) setServers(b.servers as McpServer[]);
  };

  return (
    <section className="sy-settings-ladder">
      <h3 className="sy-settings-h3">MCP servers</h3>
      <p className="sy-settings-blurb">
        Register extra <strong>MCP tool servers</strong> (a filesystem server, a
        Linear server, a local script…). They&apos;re verified when you add them
        and exposed to whichever agent CLI runs — Claude Code, Codex, Grok. Their
        tools card in the rail before running, like any other tool.
      </p>
      <div className="sy-settings-ladder-rows">
        <div className="sy-settings-editrow" style={{ display: "flex", gap: 6 }}>
          <select className="sy-settings-input sy-skills-scope" value={transport}
            onChange={(e) => setTransport(e.target.value as "stdio" | "http")}>
            <option value="stdio">stdio (command)</option>
            <option value="http">http (url)</option>
          </select>
          <input className="sy-settings-input" placeholder="name (a-z0-9_-)"
            value={name} onChange={(e) => setName(e.target.value)} />
        </div>
        {transport === "stdio" ? (
          <>
            <input className="sy-settings-input" placeholder="command (e.g. npx or an absolute path)"
              value={command} onChange={(e) => setCommand(e.target.value)} />
            <input className="sy-settings-input" placeholder="args (space-separated)"
              value={argsText} onChange={(e) => setArgsText(e.target.value)} />
          </>
        ) : (
          <input className="sy-settings-input" placeholder="https://…/mcp"
            value={url} onChange={(e) => setUrl(e.target.value)} />
        )}
        <textarea className="sy-skills-body" rows={2}
          placeholder={transport === "stdio" ? "env, one KEY=VALUE per line (optional)" : "headers, one KEY=VALUE per line (optional)"}
          value={envText} onChange={(e) => setEnvText(e.target.value)} />
      </div>
      <div className="sy-settings-ladder-actions">
        <button type="button" className="sy-confirm-btn" disabled={busy || !name.trim() || (transport === "stdio" ? !command.trim() : !url.trim())}
          onClick={() => void add()}>
          {busy ? "Verifying…" : "Add + verify"}
        </button>
        {msg && <span className={"sy-settings-status" + (msg.ok ? "" : " sy-settings-status--err")}>{msg.text}</span>}
      </div>
      {servers && servers.length > 0 && (
        <ul className="sy-agents-list" style={{ marginTop: 10 }}>
          {servers.map((s) => (
            <li key={s.name} className="sy-agents-row">
              <code className="sy-agents-name">{s.name}</code>
              <span className="sy-agents-cat">{s.transport}</span>
              <span className="sy-agents-desc">{s.command || s.url}</span>
              <span className="sy-skills-rowbtns">
                <button type="button" className="sy-skills-mini" onClick={() => void toggle(s)}>
                  {s.enabled ? "on" : "off"}
                </button>
                <button type="button" className="sy-skills-mini sy-skills-mini--del" onClick={() => void del(s)}>
                  Remove
                </button>
              </span>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}


// ── Packs panel ─────────────────────────────────────────────────────


// ── Packs panel ─────────────────────────────────────────────────────


type PackInfo = {
  name: string;
  version: string;
  description: string;
  scope: "workspace" | "user" | "system";
  path: string;
  enabled: boolean;
  skills: string[];
  tabs: { kind: string; title: string }[];
  file_routes?: { ext: string; label: string }[];
  requires_extra?: string[];
};


type RegistryEntry = {
  name: string;
  title?: string;
  description?: string;
  source: string;
  version?: string;
  requires_extra?: string[];
  homepage?: string;
};

function PacksPanel({ open }: { open: boolean }) {
  const [packs, setPacks] = useState<PackInfo[] | null>(null);
  const [registry, setRegistry] = useState<RegistryEntry[] | null>(null);
  const [source, setSource] = useState("");
  const [scope, setScope] = useState<"workspace" | "user">("user");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  const reload = async () => {
    try {
      const r = await fetch("/api/packs");
      if (!r.ok) return;
      const body = (await r.json()) as { packs: PackInfo[] };
      setPacks(body.packs);
    } catch {
      /* swallow — empty state covers it */
    }
  };

  const reloadRegistry = async () => {
    try {
      const r = await fetch("/api/packs/registry");
      if (!r.ok) return;
      const body = (await r.json()) as { packs: RegistryEntry[] };
      setRegistry(body.packs ?? []);
    } catch {
      setRegistry([]);
    }
  };

  useEffect(() => {
    if (!open) return;
    void reload();
    void reloadRegistry();
  }, [open]);

  const install = async (overrideSource?: string) => {
    const src = (overrideSource ?? source).trim();
    if (!src || busy) return;
    setBusy(true);
    setStatus(null);
    try {
      const r = await fetch("/api/packs/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: src, scope }),
      });
      const body = await r.json();
      if (!r.ok) {
        setStatus({ ok: false, msg: body.error || `HTTP ${r.status}` });
      } else {
        setStatus({ ok: true, msg: `installed ${body.pack.name}` });
        setSource("");
        await reload();
      }
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  /** Open the OS folder picker via the daemon. The same endpoint
   *  the Sheet tab's Save-as-CSV "Browse…" affordance uses — pops
   *  a native Tk dialog and returns the chosen path. */
  const browseFolder = async () => {
    if (busy) return;
    try {
      const r = await fetch("/api/workspaces/pick", { method: "POST" });
      if (!r.ok) return;
      const body = (await r.json()) as { path?: string | null };
      if (!body.path) return;
      // Auto-install from the chosen path. The daemon validates
      // there's a pack.json inside; if not, the status banner
      // surfaces the error.
      await install(body.path);
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    }
  };

  const toggle = async (p: PackInfo) => {
    // Bundled system packs are always-on EXCEPT those gated behind a
    // `requires_extra` pip install — those are opt-in and must be
    // toggleable. Mirrors the `togglable` check on the badge.
    if (p.scope === "system" && (p.requires_extra ?? []).length === 0) return;
    // Activation gate: if turning a pack on AND it declares
    // `requires_extra`, prompt for the pip install first. Declining
    // leaves the pack inactive — same end state as if the user had
    // never clicked.
    if (!p.enabled && (p.requires_extra ?? []).length > 0) {
      const extras = p.requires_extra!.join(", ");
      const ok = window.confirm(
        `Activating ${p.name} will run \`uv pip install ${extras}\` in `
        + `Switch Bay's environment. Proceed?`,
      );
      if (!ok) return;
      setBusy(true);
      setStatus({ ok: true, msg: `installing ${extras}…` });
      try {
        const r = await fetch("/api/packs/pip-install", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ packages: p.requires_extra }),
        });
        const body = await r.json();
        if (!r.ok || !body.ok) {
          setStatus({
            ok: false,
            msg: `pip install failed (rc=${body.returncode}): ${
              (body.stderr ?? body.error ?? "").slice(0, 200)
            }`,
          });
          setBusy(false);
          return;
        }
        setStatus({ ok: true, msg: `installed ${extras}` });
      } catch (e) {
        setStatus({ ok: false, msg: (e as Error).message });
        setBusy(false);
        return;
      }
      setBusy(false);
    }
    try {
      const r = await fetch("/api/packs/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: p.name, scope: p.scope, enabled: !p.enabled,
        }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({} as Record<string, string>));
        setStatus({ ok: false, msg: body.error || `HTTP ${r.status}` });
        return;
      }
      await reload();
      // A pack toggle changes the available tab kinds + file-routes,
      // which are wired at load. If the pack contributes tabs, reload so
      // they register and the new tab appears (or disappears) right away.
      if ((p.tabs ?? []).length > 0) {
        setStatus({ ok: true, msg: `${!p.enabled ? "activated" : "deactivated"} ${p.name} — reloading…` });
        window.setTimeout(() => window.location.reload(), 600);
      }
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    }
  };

  const installFromRegistry = async (entry: RegistryEntry) => {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      const src = entry.source;
      // Bundled packs are already on disk under <repo>/packs/<name>;
      // they're auto-discovered by the system-scope walker and just
      // need to be activated. Anything else gets installed via the
      // normal install pipeline.
      if (src.startsWith("bundled:")) {
        // No install needed — system-scope packs are visible the
        // moment the daemon starts. Reload to show it.
        await reload();
        setStatus({
          ok: true,
          msg: `${entry.name} is bundled — activate it from the list above.`,
        });
        return;
      }
      const r = await fetch("/api/packs/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ source: src, scope }),
      });
      const body = await r.json();
      if (!r.ok) {
        setStatus({ ok: false, msg: body.error || `HTTP ${r.status}` });
        return;
      }
      setStatus({ ok: true, msg: `installed ${entry.name}` });
      await reload();
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const remove = async (p: PackInfo) => {
    if (p.scope === "system") return;  // bundled — uninstall path blocks too
    if (!window.confirm(`Uninstall ${p.name} (${p.scope})?`)) return;
    await fetch(
      `/api/packs?name=${encodeURIComponent(p.name)}&scope=${p.scope}`,
      { method: "DELETE" },
    );
    await reload();
  };

  return (
    <section className="sy-settings-packs">
      <h3 className="sy-settings-h3">Extension packs</h3>
      <p className="sy-settings-blurb">
        Bundles of skills + tab kinds. Install from a
        git URL (<code>git clone --depth 1</code>) or a local
        directory. Workspace scope = <code>.workbench/packs/</code>;
        user scope = <code>~/.config/switchbay/packs/</code>.
        Workspace packs override user-global ones on name collision.
      </p>
      <div className="sy-settings-packs-form">
        <input
          type="text"
          value={source}
          onChange={(e) => setSource(e.target.value)}
          placeholder="git URL or /abs/path to a local pack dir"
          className="sy-settings-input"
          onKeyDown={(e) => { if (e.key === "Enter") void install(); }}
          disabled={busy}
        />
        <select
          value={scope}
          onChange={(e) => setScope(e.target.value as "workspace" | "user")}
          className="sy-settings-input"
          disabled={busy}
          title="user-global = available in every workspace; workspace = only this project"
        >
          <option value="user">user-global</option>
          <option value="workspace">workspace</option>
        </select>
        <button
          type="button"
          className="sy-confirm-btn"
          disabled={busy}
          onClick={() => void browseFolder()}
          title="Open the OS folder picker — pick a local pack directory you've cloned from GitHub"
        >
          Browse…
        </button>
        <button
          type="button"
          className="sy-confirm-btn"
          disabled={busy || !source.trim()}
          onClick={() => void install()}
        >
          {busy ? "Installing…" : "Install"}
        </button>
      </div>
      {status && (
        <p className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}>
          {status.msg}
        </p>
      )}
      {packs === null ? (
        <p className="sy-settings-blurb">Loading…</p>
      ) : packs.length === 0 ? (
        <p className="sy-settings-blurb">
          <em>No packs installed.</em> Packs bundle skills + tab kinds +
          file actions (the OWID pack is the worked example); install one
          from a git URL or local directory above.
        </p>
      ) : (
        <ul className="sy-settings-packs-list">
          {packs.map((p) => (
            <li
              key={`${p.scope}:${p.name}`}
              className={
                "sy-settings-pack"
                + (p.enabled ? "" : " sy-settings-pack--disabled")
              }
            >
              <div className="sy-settings-pack-head">
                <code className="sy-settings-pack-name">{p.name}</code>
                <span className="sy-settings-pack-ver">{p.version}</span>
                <span className="sy-settings-pack-scope">{p.scope}</span>
                <span className="sy-spacer" />
                <button
                  type="button"
                  className={
                    "sy-settings-pill"
                    + (p.enabled ? " sy-settings-pill--on" : "")
                  }
                  onClick={() => {
                    const togglable =
                      p.scope !== "system" || (p.requires_extra ?? []).length > 0;
                    if (togglable) void toggle(p);
                  }}
                  disabled={
                    p.scope === "system" && (p.requires_extra ?? []).length === 0
                  }
                  title={
                    p.scope === "system" && (p.requires_extra ?? []).length === 0
                      ? "Bundled pack — always active."
                      : p.enabled
                      ? "Click to deactivate this pack"
                      : "Click to activate this pack"
                  }
                >
                  {p.enabled ? "active" : "inactive"}
                </button>
                {p.scope !== "system" && (
                  <button
                    type="button"
                    className="sy-settings-pack-rm"
                    onClick={() => void remove(p)}
                    title="Uninstall and remove from disk"
                  >×</button>
                )}
              </div>
              {p.description && (
                <p className="sy-settings-pack-desc">{p.description}</p>
              )}
              <div className="sy-settings-pack-meta">
                {p.skills.length > 0 && <span>{p.skills.length} skill{p.skills.length === 1 ? "" : "s"}</span>}
                {p.tabs.length > 0 && <span>{p.tabs.length} tab{p.tabs.length === 1 ? "" : "s"}</span>}
                {(p.requires_extra ?? []).length > 0 && (
                  <span title="Python deps required for this pack">
                    needs: {(p.requires_extra ?? []).join(", ")}
                  </span>
                )}
              </div>
              {p.enabled
                && (p.tabs.length > 0 || (p.file_routes ?? []).length > 0 || p.skills.length > 0) && (
                <div className="sy-settings-pack-howto">
                  <span className="sy-settings-pack-howto-h">How to use</span>
                  <ul>
                    {p.tabs.map((t) => (
                      <li key={t.kind}>
                        Add the <strong>{t.title}</strong> tab from the tab strip's{" "}
                        <code>+ New…</code> menu.
                      </li>
                    ))}
                    {(p.file_routes ?? []).length > 0 && (
                      <li>
                        Right-click a{" "}
                        <code>
                          {Array.from(new Set((p.file_routes ?? []).map((r) => r.ext))).join(" / ")}
                        </code>{" "}
                        file in the Browser → <strong>{(p.file_routes ?? [])[0]?.label}</strong>.
                      </li>
                    )}
                    {p.skills.length > 0 && (
                      <li>
                        Ask in the rail, e.g. <em>“use {p.name} to …”</em> — it loads these
                        skills: <code>{p.skills.join(", ")}</code>.
                      </li>
                    )}
                  </ul>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}

      <h4 className="sy-settings-h4" style={{ marginTop: 18 }}>
        Browse available packs
      </h4>
      <p className="sy-settings-blurb">
        Switch Bay's curated registry. Run your own registry by setting{" "}
        <code>CSWY_PACK_REGISTRY</code> on the daemon — points at any
        URL serving the same shape — or skip the registry entirely
        and install from a git URL above.
      </p>
      {registry === null ? (
        <p className="sy-settings-blurb">Loading…</p>
      ) : registry.length === 0 ? (
        <p className="sy-settings-blurb">
          <em>Registry is empty.</em>
        </p>
      ) : (
        <ul className="sy-settings-packs-list">
          {registry.map((entry) => {
            const installed = (packs ?? []).some((p) => p.name === entry.name);
            return (
              <li
                key={entry.name}
                className="sy-settings-pack sy-settings-pack--registry"
              >
                <div className="sy-settings-pack-head">
                  <code className="sy-settings-pack-name">{entry.title ?? entry.name}</code>
                  {entry.version && (
                    <span className="sy-settings-pack-ver">{entry.version}</span>
                  )}
                  <span className="sy-settings-pack-scope">
                    {entry.source.startsWith("bundled:") ? "bundled" : "remote"}
                  </span>
                  <span className="sy-spacer" />
                  {installed ? (
                    <span className="sy-settings-pill">installed</span>
                  ) : (
                    <button
                      type="button"
                      className="sy-confirm-btn"
                      disabled={busy}
                      onClick={() => void installFromRegistry(entry)}
                      title={
                        entry.source.startsWith("bundled:")
                          ? "Already bundled — just activate from the list above"
                          : `Install from ${entry.source}`
                      }
                    >
                      {entry.source.startsWith("bundled:") ? "Reveal" : "Install"}
                    </button>
                  )}
                </div>
                {entry.description && (
                  <p className="sy-settings-pack-desc">{entry.description}</p>
                )}
                <div className="sy-settings-pack-meta">
                  {(entry.requires_extra ?? []).length > 0 && (
                    <span title="Pip-installed on activation">
                      needs: {(entry.requires_extra ?? []).join(", ")}
                    </span>
                  )}
                  {entry.homepage && (
                    <a href={entry.homepage} target="_blank" rel="noreferrer">
                      homepage
                    </a>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

// ── User Tabs panel ─────────────────────────────────────────────────


type UserTab = {
  id: string;
  title: string;
  kind: string;
  description: string;
  enabled: boolean;
};


function UserTabsPanel({ open }: { open: boolean }) {
  const [tabs, setTabs] = useState<UserTab[] | null>(null);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  const reload = async () => {
    try {
      const r = await fetch("/api/user-tabs");
      if (!r.ok) return;
      const body = (await r.json()) as { tabs: UserTab[] };
      setTabs(body.tabs);
    } catch {
      /* empty state covers it */
    }
  };

  useEffect(() => {
    if (!open) return;
    void reload();
  }, [open]);

  const toggle = async (t: UserTab) => {
    try {
      const r = await fetch("/api/user-tabs/toggle", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: t.id, enabled: !t.enabled }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({} as Record<string, string>));
        setStatus({ ok: false, msg: body.error || `HTTP ${r.status}` });
        return;
      }
      await reload();
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    }
  };

  return (
    <section className="sy-settings-packs">
      <h3 className="sy-settings-h3">User tabs</h3>
      <p className="sy-settings-blurb">
        Tabs in <code>.workbench/mode.json</code> that aren't part of
        the default workbench layout and didn't come from an extension
        pack. Soft-disable hides a tab from the strip without removing
        it from <code>mode.json</code>. Add new ones via the
        tab-strip's <code>+ New…</code> affordance (drops a how-to in
        the rail).
      </p>
      {status && (
        <p className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}>
          {status.msg}
        </p>
      )}
      {tabs === null ? (
        <p className="sy-settings-blurb">Loading…</p>
      ) : tabs.length === 0 ? (
        <p className="sy-settings-blurb">
          <em>No user tabs in this workspace.</em> The eight default
          tabs (Graph, Editor, Table, Sheet, Plot, Sketch, Projects,
          Agents) ship with Switch Bay and can't be toggled here.
        </p>
      ) : (
        <ul className="sy-settings-packs-list">
          {tabs.map((t) => (
            <li
              key={t.id}
              className={
                "sy-settings-pack"
                + (t.enabled ? "" : " sy-settings-pack--disabled")
              }
            >
              <div className="sy-settings-pack-head">
                <code className="sy-settings-pack-name">{t.title}</code>
                <span className="sy-settings-pack-ver">{t.kind}</span>
                <span className="sy-settings-pack-scope">user</span>
                <span className="sy-spacer" />
                <button
                  type="button"
                  className={
                    "sy-settings-pill"
                    + (t.enabled ? " sy-settings-pill--on" : "")
                  }
                  onClick={() => void toggle(t)}
                  title={
                    t.enabled
                      ? "Click to hide this tab from the strip"
                      : "Click to show this tab in the strip"
                  }
                >
                  {t.enabled ? "active" : "inactive"}
                </button>
              </div>
              <p className="sy-settings-pack-desc">{t.description}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}


// ── Permissions panel ──────────────────────────────────────────────


function PermissionsPanel({ open }: { open: boolean }) {
  const [patterns, setPatterns] = useState<string[] | null>(null);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  const reload = async () => {
    try {
      const r = await fetch("/api/permission/allow");
      if (!r.ok) return;
      const body = (await r.json()) as { patterns: string[] };
      setPatterns(body.patterns);
    } catch {
      setPatterns([]);
    }
  };

  useEffect(() => {
    if (!open) return;
    void reload();
  }, [open]);

  const revoke = async (pat: string) => {
    if (!window.confirm(`Revoke approval for "${pat}"?`)) return;
    try {
      const r = await fetch(
        `/api/permission/allow?pattern=${encodeURIComponent(pat)}`,
        { method: "DELETE" },
      );
      if (!r.ok) {
        const body = await r.json().catch(() => ({} as Record<string, string>));
        setStatus({ ok: false, msg: body.error || `HTTP ${r.status}` });
        return;
      }
      await reload();
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    }
  };

  // The Codex "elevated sandbox" sentinel — a fixed pattern that
  // codex's spawn-time check looks for. Toggle adds/removes it
  // directly via the allow-list endpoint; codex's next spawn picks
  // up the change without further plumbing.
  const codexFullAccess = (patterns ?? []).includes("_codex:full-access");
  const toggleCodexFullAccess = async () => {
    if (codexFullAccess) {
      await revoke("_codex:full-access");
      return;
    }
    if (!window.confirm(
      "Allow codex to run with full filesystem + network access in this workspace? "
      + "This bypasses codex's default workspace-write sandbox. Only enable if you "
      + "trust the prompts you're running.",
    )) return;
    try {
      const r = await fetch("/api/permission/allow", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pattern: "_codex:full-access" }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({} as Record<string, string>));
        setStatus({ ok: false, msg: body.error || `HTTP ${r.status}` });
        return;
      }
      await reload();
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    }
  };

  return (
    <section className="sy-settings-packs">
      <h3 className="sy-settings-h3">Permissions</h3>
      <p className="sy-settings-blurb">
        Tool-call approvals you've remembered for this workspace.
        When the rail's permission dialog asks you to allow a command
        (e.g. <code>Bash(npm test*)</code>) and you click
        <code> Approve + remember</code>, the pattern lands here.
        Pattern shape mirrors claude-code's allowlist syntax — wildcards
        cover the trailing arguments. Revoking drops the approval; the
        next matching tool call will prompt again.
      </p>
      {status && (
        <p className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}>
          {status.msg}
        </p>
      )}
      {patterns === null ? (
        <p className="sy-settings-blurb">Loading…</p>
      ) : patterns.length === 0 ? (
        <p className="sy-settings-blurb">
          <em>No remembered approvals yet.</em> Approvals accumulate as
          you grant agent tool calls in the rail.
        </p>
      ) : (
        <ul className="sy-settings-perm-list">
          {patterns.map((pat) => (
            <li key={pat} className="sy-settings-perm-row">
              <code className="sy-settings-perm-pat">{pat}</code>
              <span className="sy-spacer" />
              <button
                type="button"
                className="sy-confirm-btn"
                onClick={() => void revoke(pat)}
                title="Drop this approval — the next matching tool call will prompt again"
              >
                Revoke
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="sy-settings-perm-row sy-settings-perm-row--codex">
        <span>
          <strong>Codex sandbox:</strong>{" "}
          {codexFullAccess
            ? "danger-full-access (every spawn)"
            : "workspace-write (default)"}
        </span>
        <span className="sy-spacer" />
        <button
          type="button"
          className={
            "sy-settings-pill"
            + (codexFullAccess ? " sy-settings-pill--on" : "")
          }
          onClick={() => void toggleCodexFullAccess()}
          title={
            codexFullAccess
              ? "Revert to workspace-write — codex won't be able to reach network or paths outside the workspace"
              : "Elevate this workspace's codex spawns to full access"
          }
        >
          {codexFullAccess ? "elevated" : "default"}
        </button>
      </div>
      <p className="sy-settings-blurb" style={{ marginTop: 8 }}>
        Codex has no per-tool hook surface like Claude Code, so
        per-command gating isn't possible. The toggle above is the
        only sandbox knob — flip it when a prompt needs network or
        out-of-workspace writes.
      </p>
    </section>
  );
}


// ── Storage panel ───────────────────────────────────────────────────


type MediaProviderOpt = {
  id: string;
  label: string;
  models: string[];
  default_model: string;
  has_key: boolean;
};

type MediaModalityState = {
  blurb?: string;
  providers: MediaProviderOpt[];
  choice: { provider: string; model: string } | null;
  available: boolean;
};

type SettingsBody = {
  rail_history_local: boolean;
  rail_history_path: string;
  workspace_synced: string | null;
  embedding_backend?: string;
  embedding_vendors_keyed?: Record<string, boolean>;
  media?: {
    modalities?: Record<string, MediaModalityState>;
    note?: string;
  };
};

// ── GitHub Copilot sign-in (device flow — browser login / SSO) ─────

function CopilotAuth({ authed, onChanged }: { authed: boolean; onChanged: () => void }) {
  const [pending, setPending] = useState<
    {
      code: string; uri: string; host?: string;
      ssoHint?: string; ssoUri?: string;
    } | null
  >(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Enterprise deployments (GHES, <slug>.ghe.com) and EMU accounts on
  // github.com need a host / SSO URL before the device code binds to
  // the right identity. Personal accounts leave the field blank.
  const [showEnterprise, setShowEnterprise] = useState(false);
  const [host, setHost] = useState("");

  // Open a URL in the same browser via a real <a> click. window.open
  // with "noopener" returns null; a blank pre-opened URL throws
  // OSStatus -50 in a PWA.
  const openInBrowser = (url: string) => {
    if (!url) return;
    const a = document.createElement("a");
    a.href = url;
    a.target = "_blank";
    a.rel = "noreferrer";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  // Poll while a sign-in is out; GitHub grants land daemon-side.
  useEffect(() => {
    if (!pending) return;
    const iv = window.setInterval(async () => {
      try {
        const r = await fetch("/api/copilot/login/status");
        if (!r.ok) return;
        const b = (await r.json()) as {
          authed: boolean; login?: { state: string; error?: string | null } | null;
        };
        if (b.authed) {
          setPending(null);
          onChanged();
        } else if (b.login?.state === "error" || b.login?.state === "cancelled") {
          setPending(null);
          setErr(b.login.error || "sign-in failed");
        }
      } catch { /* transient */ }
    }, 3000);
    return () => window.clearInterval(iv);
  }, [pending, onChanged]);

  const start = async (opts?: { enterprise?: boolean }) => {
    if (busy) return;
    const useEnterprise = !!opts?.enterprise || showEnterprise;
    if (useEnterprise && !host.trim()) {
      setShowEnterprise(true);
      setErr("Enter your enterprise SSO URL or host, then Sign in.");
      return;
    }
    setBusy(true);
    setErr(null);
    try {
      const r = await fetch("/api/copilot/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          useEnterprise && host.trim() ? { host: host.trim() } : {},
        ),
      });
      const b = await r.json().catch(() => ({} as Record<string, unknown>));
      if (!r.ok) {
        setErr(String((b as { error?: string }).error || r.status));
        return;
      }
      const body = b as {
        user_code?: string; verification_uri?: string;
        host?: string; sso_hint?: string; sso_uri?: string;
      };
      const code = String(body.user_code ?? "");
      const uri = String(body.verification_uri ?? "");
      const ssoUri = String(body.sso_uri || "").trim();
      const ssoHint = String(body.sso_hint || "").trim();
      setPending({
        code, uri, host: body.host,
        ssoHint: ssoHint || undefined,
        ssoUri: ssoUri || undefined,
      });
      // EMU: open SSO first (same browser) so the device-code page
      // binds to the enterprise IdP session — cold /login/device only
      // shows password/Google.
      if (ssoUri && !ssoUri.includes("<your-enterprise>")) {
        openInBrowser(ssoUri);
      } else {
        openInBrowser(uri);
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const cancel = async () => {
    await fetch("/api/copilot/login/cancel", { method: "POST" }).catch(() => null);
    setPending(null);
    setErr(null);
  };

  const signOut = async () => {
    await fetch("/api/copilot/logout", { method: "POST" }).catch(() => null);
    onChanged();
  };

  if (authed) {
    return (
      <div className="sy-copilot-auth-actions">
        <button type="button" className="sy-confirm-btn" onClick={() => void signOut()}>
          Sign out
        </button>
      </div>
    );
  }

  return (
    <div className="sy-copilot-auth">
      {pending ? (
        <div className="sy-copilot-pending">
          {pending.ssoUri && !pending.ssoUri.includes("<your-enterprise>") ? (
            <>
              <div>
                <strong>1.</strong> Complete SSO in the same browser:{" "}
                <a href={pending.ssoUri} target="_blank" rel="noreferrer">
                  {pending.ssoUri}
                </a>
              </div>
              <div>
                <strong>2.</strong> Enter code <code>{pending.code}</code> at{" "}
                <a href={pending.uri} target="_blank" rel="noreferrer">{pending.uri}</a>
                {" "}— waiting for GitHub…
              </div>
            </>
          ) : (
            <div>
              Enter code <code>{pending.code}</code> at{" "}
              <a href={pending.uri} target="_blank" rel="noreferrer">{pending.uri}</a>
              {" "}— waiting for GitHub…
            </div>
          )}
          {pending.ssoHint && !pending.ssoUri && (
            <div>
              Wrong account? Sign in at <code>{pending.ssoHint}</code> first,
              then Cancel and retry.
            </div>
          )}
          <div className="sy-copilot-pending-actions">
            {pending.ssoUri && !pending.ssoUri.includes("<your-enterprise>") && (
              <a
                className="sy-confirm-btn"
                href={pending.ssoUri}
                target="_blank"
                rel="noreferrer"
              >
                Open SSO
              </a>
            )}
            <a
              className="sy-confirm-btn sy-confirm-btn--primary"
              href={pending.uri}
              target="_blank"
              rel="noreferrer"
            >
              Open code page
            </a>
            <button
              type="button"
              className="sy-confirm-btn"
              onClick={() => void cancel()}
              title="Cancel and free the sign-in slot for a retry"
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="sy-copilot-auth-actions">
            <button
              type="button"
              className="sy-confirm-btn sy-confirm-btn--primary"
              onClick={() => void start({ enterprise: false })}
              disabled={busy}
              title="Personal github.com account"
            >
              {busy && !showEnterprise ? "Starting…" : "Sign in with GitHub"}
            </button>
            <button
              type="button"
              className={
                "sy-confirm-btn" + (showEnterprise ? " sy-confirm-btn--primary" : "")
              }
              onClick={() => {
                setShowEnterprise((v) => !v);
                setErr(null);
              }}
              title="GitHub Enterprise Server, ghe.com, or EMU SSO"
            >
              Enterprise…
            </button>
          </div>
          {showEnterprise && (
            <div className="sy-copilot-enterprise">
              <label htmlFor="sy-copilot-host">Enterprise SSO URL or host</label>
              <input
                id="sy-copilot-host"
                type="text"
                className="sy-ws-input"
                value={host}
                placeholder="github.com/enterprises/acme  or  acme.ghe.com"
                onChange={(e) => setHost(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void start({ enterprise: true });
                  }
                }}
                autoComplete="off"
                spellCheck={false}
              />
              <p className="sy-settings-blurb">
                <strong>Personal:</strong> leave this closed and use{" "}
                <em>Sign in with GitHub</em>.
                <br />
                <strong>EMU / org SSO:</strong> paste{" "}
                <code>github.com/enterprises/&lt;slug&gt;/sso</code>, then Sign in —
                we open SSO first, then the device code (same browser).
                <br />
                <strong>GHES / ghe.com:</strong> paste the host only
                (e.g. <code>acme.ghe.com</code>).
              </p>
              <div className="sy-copilot-auth-actions">
                <button
                  type="button"
                  className="sy-confirm-btn sy-confirm-btn--primary"
                  onClick={() => void start({ enterprise: true })}
                  disabled={busy || !host.trim()}
                >
                  {busy ? "Starting…" : "Sign in with Enterprise"}
                </button>
              </div>
            </div>
          )}
        </>
      )}
      {err && (
        <span className="sy-settings-status sy-settings-status--err" style={{ margin: 0 }}>
          {err}
        </span>
      )}
    </div>
  );
}


// ── Local agent model panel (llama.cpp / MLX / Ollama) ───────────────
// One section: pick a server type, see installed models for it, then
// search/install. Cloud providers stay above; no duplicate local cards.

type LocalBackendId = "llamacpp" | "mlx" | "ollama";

type LocalInstalled = {
  id: string;
  label?: string;
  backend?: string;
  quant?: string;
  ctx?: number;
  port?: number;
  alias?: string;
  file?: string;
  ollama_tag?: string;
  repo?: string;
  local_path?: string;
  source?: string;
};

type LocalServer = {
  id: string;
  port?: number;
  alive?: boolean;
  pid?: number | null;
  alias?: string;
  model_label?: string;
  backend?: string;
  orphan?: boolean;
};

type LocalBackends = {
  llamacpp?: { available?: boolean; label?: string };
  ollama?: { available?: boolean; label?: string; hint?: string };
  mlx?: {
    supported?: boolean; installed?: boolean; label?: string;
    reason?: string; install_hint?: string; version?: string | null;
    binary?: string | null;
  };
};

type SearchHit = {
  repo: string;
  author?: string;
  downloads?: number | null;
  likes?: number | null;
  trending?: number | null;
  last_modified?: string | null;
  trusted?: boolean;
  off_task?: boolean;
  /** UI rank tag after client-side ranking */
  _tier?: "exact" | "match" | "alt";
};

type ResolvedCand = {
  ok?: boolean;
  error?: string;
  id?: string;
  label?: string;
  backend?: string;
  repo?: string;
  ollama_tag?: string;
  quant?: string;
  weights_gb?: number;
  est_gb?: number;
  fits?: boolean;
  installed?: boolean;
  off_task?: boolean;
  trusted?: boolean;
  quants_available?: string[];
};

type LocalLlmBody = {
  plan: {
    ok: boolean;
    ram_gb: number;
    reason?: string;
    model_label?: string;
    quant?: string;
    ctx?: number;
    est_gb?: number;
    weights_gb?: number;
    ctx_options?: { ctx: number; est_gb: number; recommended?: boolean; experimental?: boolean }[];
  };
  top3?: { ok?: boolean; candidates?: unknown[]; reason?: string; ram_gb?: number };
  installed?: LocalInstalled[];
  active?: string | null;
  servers?: LocalServer[];
  server_url?: string | null;
  backends?: LocalBackends;
  config?: {
    model_label?: string;
    quant?: string;
    ctx?: number;
    port?: number;
    reasoning?: boolean;
    candidate_id?: string;
    alias?: string;
    backend?: string;
  } | null;
  server_healthy?: boolean;
  install?: {
    state?: string;
    step?: string;
    percent?: number;
    error?: string | null;
    candidate_id?: string;
  } | null;
  local_rung?: {
    id?: string;
    label?: string;
    prompt_budget?: number;
    force_scaffold?: boolean;
    recommended_ctx?: number;
    n_tools_curate?: number;
    blurb?: string;
  } | null;
};

type SortKey = "downloads" | "trendingScore" | "lastModified";

/** Rank HF search hits for the install list (settings "rail"). */
function rankLocalSearchHits(
  query: string,
  hits: SearchHit[],
  sort: SortKey,
): SearchHit[] {
  const q = query.trim().toLowerCase();
  const bySort = (a: SearchHit, b: SearchHit) => {
    if (sort === "trendingScore") {
      return (Number(b.trending) || 0) - (Number(a.trending) || 0);
    }
    if (sort === "lastModified") {
      return String(b.last_modified || "").localeCompare(String(a.last_modified || ""));
    }
    return (Number(b.downloads) || 0) - (Number(a.downloads) || 0);
  };

  // Blank query: up to 8, already sorted by API.
  if (!q) {
    return hits.slice(0, 8).map((h) => ({ ...h, _tier: "match" as const }));
  }

  const exact = hits.filter((h) => h.repo.toLowerCase() === q);
  const partial = hits
    .filter((h) => {
      const r = h.repo.toLowerCase();
      return r !== q && (r.includes(q) || r.endsWith("/" + q) || r.split("/")[1] === q);
    })
    .sort(bySort);

  // Unambiguous exact (or sole partial that equals path segment)
  if (exact.length === 1 && partial.length === 0) {
    const alts = hits
      .filter((h) => h.repo !== exact[0].repo)
      .sort(bySort)
      .slice(0, 3)
      .map((h) => ({ ...h, _tier: "alt" as const }));
    return [{ ...exact[0], _tier: "exact" }, ...alts];
  }
  if (exact.length === 1) {
    const alts = partial.slice(0, 3).map((h) => ({ ...h, _tier: "alt" as const }));
    // If few partials, pad with non-match top downloads
    if (alts.length < 3) {
      const used = new Set([exact[0].repo, ...alts.map((a) => a.repo)]);
      for (const h of [...hits].sort(bySort)) {
        if (used.has(h.repo)) continue;
        alts.push({ ...h, _tier: "alt" });
        if (alts.length >= 3) break;
      }
    }
    return [{ ...exact[0], _tier: "exact" }, ...alts];
  }

  // Multiple matches: up to 5 matches, then up to 3 alternatives
  const matches = (exact.length ? exact : partial).slice(0, 5)
    .map((h) => ({ ...h, _tier: (exact.some((e) => e.repo === h.repo) ? "exact" : "match") as SearchHit["_tier"] }));
  const used = new Set(matches.map((m) => m.repo));
  const alts: SearchHit[] = [];
  for (const h of [...hits].sort(bySort)) {
    if (used.has(h.repo)) continue;
    alts.push({ ...h, _tier: "alt" });
    if (alts.length >= 3) break;
  }
  if (matches.length === 0) {
    // No string matches — show top 8 by sort as soft results
    return hits.slice(0, 8).map((h) => ({ ...h, _tier: "match" as const }));
  }
  return [...matches, ...alts];
}

function isCacheDiscovered(m: LocalInstalled): boolean {
  const src = m.source || "";
  return src === "app-cache" || src === "hf-cache" || src.endsWith("-cache");
}

function cacheSourceCaption(m: LocalInstalled): string {
  const repo = m.repo || "";
  if (m.source === "app-cache") {
    return repo
      ? `Already on disk (another app · ${repo})`
      : "Already on disk (another app)";
  }
  return repo ? `Already on disk · ${repo}` : "Already on disk";
}

function LocalModelPanel({
  open, onClose, hfDownloads = true,
}: {
  open: boolean;
  onClose: () => void;
  hfDownloads?: boolean;
}) {
  const [body, setBody] = useState<LocalLlmBody | null>(null);
  const [backend, setBackend] = useState<LocalBackendId>("llamacpp");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<SortKey>("downloads");
  const [hits, setHits] = useState<SearchHit[] | null>(null);
  const [searchNote, setSearchNote] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "search" | "install" | "activate" | "remove" | "other">("");
  const [warmingId, setWarmingId] = useState<string | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [keepOthers, setKeepOthers] = useState(true);
  const sectionRef = useRef<HTMLElement>(null);
  const [harness, setHarness] = useState<{ text: string; lines: number; refine_lines: number; path: string } | null>(null);
  const [harnessDraft, setHarnessDraft] = useState("");
  const [harnessSaved, setHarnessSaved] = useState(false);

  useEffect(() => {
    const onFocus = (ev: Event) => {
      const detail = (ev as CustomEvent<{ backend?: string }>).detail;
      const b = detail?.backend;
      if (b === "mlx" || b === "llamacpp" || b === "ollama") setBackend(b);
      sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "center" });
    };
    window.addEventListener("sy:focus-localllm-install", onFocus);
    return () => window.removeEventListener("sy:focus-localllm-install", onFocus);
  }, []);

  const load = async () => {
    try {
      const r = await fetch("/api/localllm/status");
      if (!r.ok) return null;
      const b = (await r.json()) as LocalLlmBody;
      setBody(b);
      return b;
    } catch {
      return null;
    }
  };

  const [backendReady, setBackendReady] = useState(false);

  useEffect(() => {
    if (!open) {
      setBackendReady(false);
      return;
    }
    void (async () => {
      const b = await load();
      if (!b || backendReady) return;
      const fromCfg = b.config?.backend;
      const fromActive = (b.installed || []).find((m) => m.id === b.active)?.backend;
      const pick = fromCfg || fromActive;
      const diskMlx = (b.installed || []).some(
        (m) => m.backend === "mlx" && isCacheDiscovered(m),
      );
      // Surface weights already on disk even when the active local
      // server is still llama.cpp.
      if (diskMlx && pick !== "mlx") {
        setBackend("mlx");
      } else if (pick === "mlx" || pick === "llamacpp" || pick === "ollama") {
        setBackend(pick);
      }
      setBackendReady(true);
      if (diskMlx) {
        window.requestAnimationFrame(() => {
          sectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
        });
      }
    })();
  }, [open, backendReady]);

  const installing = body?.install?.state === "running";
  useEffect(() => {
    if (!open) return;
    const iv = window.setInterval(
      () => void load(),
      installing || warmingId ? 1000 : 4000,
    );
    return () => window.clearInterval(iv);
  }, [open, installing, warmingId]);

  useEffect(() => {
    if (!warmingId || !body) return;
    const m = (body.installed || []).find((row) => row.id === warmingId);
    const server = (body.servers || []).find((s) =>
      s.id === warmingId
      || (m?.alias && s.alias === m.alias)
      || (m?.port != null && s.port === m.port),
    );
    const alive = !!server?.alive;
    const ready = alive && !!body.server_healthy && (
      body.active === warmingId
      || (m?.alias && body.config?.alias === m.alias)
    );
    if (ready) setWarmingId(null);
  }, [body, warmingId]);

  useEffect(() => {
    if (!open) return;
    void fetch("/api/localllm/harness")
      .then((r) => (r.ok ? r.json() : null))
      .then((h) => { if (h) { setHarness(h); setHarnessDraft(h.text); } })
      .catch(() => { /* older daemon */ });
  }, [open]);

  // Clear results when switching server type
  useEffect(() => {
    setHits(null);
    setSearchNote(null);
    setErr(null);
    setQuery("");
  }, [backend]);

  const backends = body?.backends;
  const mlxSupported = !!backends?.mlx?.supported;
  const mlxInstalled = !!backends?.mlx?.installed;
  const ollamaOk = !!backends?.ollama?.available;
  const ram = body?.top3?.ram_gb ?? body?.plan?.ram_gb ?? 16;

  const installedForBackend = (body?.installed ?? []).filter((m) => {
    const b = m.backend || "llamacpp";
    return b === backend;
  });
  const mlxOnDisk = (body?.installed ?? []).filter(
    (m) => m.backend === "mlx" && isCacheDiscovered(m),
  );

  const runSearch = async () => {
    setBusy("search");
    setErr(null);
    setHits(null);
    setSearchNote(null);
    try {
      if (backend === "ollama") {
        const tag = query.trim();
        if (!tag) {
          setSearchNote(
            "Ollama has no public search index — paste a library tag (e.g. qwen2.5-coder:7b) and Search to resolve it.",
          );
          setHits([]);
          return;
        }
        const r = await fetch("/api/local-models/resolve", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ backend: "ollama", ollama_tag: tag }),
        });
        const b = (await r.json().catch(() => ({}))) as ResolvedCand;
        if (!r.ok || !b.ok) {
          setErr(b.error || `HTTP ${r.status}`);
          setHits([]);
          return;
        }
        setHits([{
          repo: String(b.ollama_tag || tag),
          author: "ollama",
          _tier: "exact",
          trusted: true,
        }]);
        setSearchNote("Resolved Ollama tag — Install to pull.");
        return;
      }

      if (backend === "mlx" && !mlxInstalled) {
        setErr(
          `MLX runtime not on PATH. Install with: ${
            backends?.mlx?.install_hint || "uv tool install mlx-lm"
          }`,
        );
        setHits([]);
        return;
      }

      const q = query.trim();
      // Over-fetch so client ranking can pick matches + alternatives.
      const limit = q ? "40" : "8";
      const qs = new URLSearchParams({
        q, backend, sort, limit,
      });
      const r = await fetch(`/api/local-models/search?${qs}`);
      const b = await r.json().catch(() => ({} as {
        error?: string; results?: SearchHit[];
      }));
      if (!r.ok) {
        setErr(String(b.error || `HTTP ${r.status}`));
        setHits([]);
        return;
      }
      if (b.error) {
        setErr(String(b.error));
        setHits((b.results || []) as SearchHit[]);
        return;
      }
      const raw = (b.results || []) as SearchHit[];
      const ranked = rankLocalSearchHits(q, raw, sort);
      setHits(ranked);
      if (ranked.length === 0) {
        setSearchNote(q ? "No matches." : "No models returned.");
      } else if (!q) {
        setSearchNote(`Top ${ranked.length} by ${
          sort === "downloads" ? "downloads"
            : sort === "trendingScore" ? "trending"
              : "recent updates"
        }.`);
      } else {
        const nExact = ranked.filter((h) => h._tier === "exact").length;
        const nMatch = ranked.filter((h) => h._tier === "match").length;
        const nAlt = ranked.filter((h) => h._tier === "alt").length;
        if (nExact && nMatch + nAlt) {
          setSearchNote(
            nExact === 1
              ? "Exact match first, then similar alternatives."
              : `${nExact} close matches, then alternatives.`,
          );
        } else if (nMatch && nAlt) {
          setSearchNote(`Up to ${nMatch} matches, then ${nAlt} alternatives.`);
        } else {
          setSearchNote(null);
        }
      }
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const installHit = async (hit: SearchHit) => {
    setBusy("install");
    setErr(null);
    try {
      if (backend === "ollama") {
        const r = await fetch("/api/localllm/install", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ backend: "ollama", ollama_tag: hit.repo }),
        });
        const b = await r.json().catch(() => ({} as { error?: string }));
        if (!r.ok) { setErr(b.error || `HTTP ${r.status}`); return; }
        void load();
        return;
      }
      // Resolve first so we get a real quant/size, then install.
      const res = await fetch("/api/local-models/resolve", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backend, repo: hit.repo }),
      });
      const cand = (await res.json().catch(() => ({}))) as ResolvedCand;
      if (!res.ok || !cand.ok) {
        setErr(cand.error || `resolve: HTTP ${res.status}`);
        return;
      }
      const r = await fetch("/api/localllm/install", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          backend, repo: cand.repo || hit.repo, quant: cand.quant,
        }),
      });
      const b = await r.json().catch(() => ({} as { error?: string }));
      if (!r.ok) { setErr(b.error || `HTTP ${r.status}`); return; }
      void load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const activate = async (id: string) => {
    setBusy("activate");
    setWarmingId(id);
    setErr(null);
    setNote(null);
    try {
      const r = await fetch("/api/local-models/activate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, keep_others: keepOthers }),
      });
      const b = await r.json().catch(() => ({} as { error?: string }));
      if (!r.ok) {
        setErr(b.error || `activate: HTTP ${r.status}`);
        setWarmingId(null);
        return;
      }
      void load();
    } catch (e) {
      setErr((e as Error).message);
      setWarmingId(null);
    } finally {
      setBusy("");
    }
  };

  const removeModel = async (id: string) => {
    if (!window.confirm(`Remove local model “${id}”?`)) return;
    setBusy("remove");
    setErr(null);
    try {
      const r = await fetch("/api/local-models/remove", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id }),
      });
      const b = await r.json().catch(() => ({} as { error?: string }));
      if (!r.ok) { setErr(b.error || `remove: HTTP ${r.status}`); return; }
      void load();
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy("");
    }
  };

  const toggleReasoning = async (enabled: boolean) => {
    try {
      const r = await fetch("/api/localllm/reasoning", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled }),
      });
      if (!r.ok) { setErr(`reasoning toggle: HTTP ${r.status}`); return; }
      void load();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const controlServer = async (id: string, action: "start" | "stop" | "restart") => {
    setBusy("other");
    setWarmingId(action === "stop" ? null : id);
    setErr(null);
    setNote(null);
    try {
      const r = await fetch("/api/localllm/control", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id, action }),
      });
      const b = await r.json().catch(() => ({})) as {
        error?: string; server_healthy?: boolean; servers?: LocalServer[];
      };
      if (!r.ok) {
        setErr(b.error || `HTTP ${r.status}`);
        setWarmingId(null);
        return;
      }
      const live = (b.servers || []).some((s: LocalServer) => s.alive);
      if (action === "stop") {
        setNote("Stopped.");
      } else if (b.server_healthy && live) {
        setNote(action === "restart" ? "Restarted — serving." : "Started — serving.");
      } else if (live) {
        setNote("Process is up — still loading weights. Use Watch server for progress.");
      } else {
        setErr("Server process did not stay running. Watch server for the log.");
      }
      void load();
    } catch (e) {
      setErr((e as Error).message);
      setWarmingId(null);
    } finally {
      setBusy("");
    }
  };

  const watch = async (id?: string) => {
    try {
      const r = await fetch("/api/localllm/watch", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          id: id || body?.active || body?.config?.candidate_id || undefined,
        }),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({} as { error?: string }));
        setErr(b.error || `HTTP ${r.status}`);
        return;
      }
      onClose();
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  const saveHarness = async () => {
    try {
      const r = await fetch("/api/localllm/harness", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: harnessDraft }),
      });
      if (!r.ok) { setErr(`harness save: HTTP ${r.status}`); return; }
      const h = await r.json();
      setHarness(h); setHarnessDraft(h.text);
      setHarnessSaved(true);
      window.setTimeout(() => setHarnessSaved(false), 1500);
    } catch (e) {
      setErr((e as Error).message);
    }
  };

  if (body === null) return null;
  const config = body.config;
  const inst = body.install;
  const activeBackend = (config?.backend as LocalBackendId | undefined) || "llamacpp";

  const backendButtons: {
    id: LocalBackendId; label: string; disabled: boolean; title: string;
  }[] = [
    {
      id: "llamacpp",
      label: "llama.cpp",
      disabled: false,
      title: "Managed llama-server · GGUF models from Hugging Face",
    },
    {
      id: "mlx",
      label: mlxSupported
        ? (!mlxInstalled
          ? "MLX · needs mlx-lm"
          : mlxOnDisk.length
            ? `MLX · ${mlxOnDisk.length} on disk`
            : "MLX")
        : "MLX",
      disabled: !mlxSupported,
      title: !mlxSupported
        ? (backends?.mlx?.reason || "Apple silicon only")
        : !mlxInstalled
          ? (backends?.mlx?.install_hint || "uv tool install mlx-lm")
          : mlxOnDisk.length
            ? `${mlxOnDisk.map((m) => m.label || m.repo).join(", ")} already on this Mac`
            : "Apple-silicon MLX models from Hugging Face",
    },
    {
      id: "ollama",
      label: "Ollama",
      disabled: !ollamaOk,
      title: ollamaOk
        ? "Ollama tags from the local library"
        : "Install Ollama to enable",
    },
  ];

  return (
    <section className="sy-settings-packs" ref={sectionRef}>
      <h3 className="sy-settings-h3">Local agent model</h3>
      <p className="sy-settings-blurb">
        Run models on this machine (~{ram} GB RAM). Pick a server type.
        Installing points ladder <strong>trivial + normal</strong> at the
        local model.
      </p>
      {body.local_rung && (
        <p className="sy-settings-blurb">
          Local curate desk: <strong>{body.local_rung.label}</strong>
          {body.local_rung.n_tools_curate != null
            ? ` · ${body.local_rung.n_tools_curate} tools`
            : ""}
          {body.local_rung.prompt_budget != null
            ? ` · ~${body.local_rung.prompt_budget} token budget`
            : ""}
          {body.local_rung.recommended_ctx != null
            ? ` · ${Math.round(body.local_rung.recommended_ctx / 1024)}k ctx`
            : ""}
          {body.local_rung.force_scaffold ? " · scaffolds only" : " · sourced pages ok"}
          {body.local_rung.blurb ? ` — ${body.local_rung.blurb}` : ""}
        </p>
      )}

      {/* Server type */}
      <div className="sy-copilot-auth-actions" style={{ marginBottom: 10 }}>
        {backendButtons.map((b) => (
          <button
            key={b.id}
            type="button"
            className={
              backend === b.id
                ? "sy-confirm-btn sy-confirm-btn--primary"
                : "sy-confirm-btn"
            }
            disabled={b.disabled}
            title={b.title}
            onClick={() => setBackend(b.id)}
          >
            {b.label}
          </button>
        ))}
      </div>

      {backend !== "mlx" && mlxOnDisk.length > 0 && (
        <p className="sy-settings-blurb">
          Found {mlxOnDisk.map((m) => m.label || m.repo).join(", ")} already
          on this Mac.{" "}
          <button
            type="button"
            className="sy-confirm-btn"
            onClick={() => setBackend("mlx")}
          >
            Show in MLX
          </button>
        </p>
      )}

      {/* Installed for this backend — above blurbs so on-disk finds
          aren't pushed under the footer. */}
      {installedForBackend.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div className="sy-settings-blurb" style={{ fontWeight: 600 }}>
            Installed · {backend === "llamacpp" ? "llama.cpp" : backend === "mlx" ? "MLX" : "Ollama"}
          </div>
          {backend === "llamacpp" && (
            <label
              style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 6, marginBottom: 8 }}
            >
              <input
                type="checkbox"
                checked={keepOthers}
                onChange={(e) => setKeepOthers(e.target.checked)}
              />
              Keep other servers running when switching
            </label>
          )}
          {installedForBackend.map((m) => {
            const isActive = (body.active || config?.candidate_id) === m.id
              || !!(config?.alias && m.alias && config.alias === m.alias);
            const server = (body.servers || []).find((s) =>
              s.id === m.id
              || (m.alias && s.alias === m.alias)
              || (m.port != null && s.port === m.port),
            );
            const port = m.port ?? server?.port ?? (isActive ? config?.port : undefined);
            const processAlive = !!server?.alive;
            const serving = processAlive && (isActive ? !!body.server_healthy : true);
            const warming = warmingId === m.id
              || (inst?.state === "running" && inst.candidate_id === m.id);
            const loadPct = (inst?.state === "running" && inst.candidate_id === m.id)
              ? inst.percent
              : undefined;
            const statusLine = m.backend === "ollama"
              ? `Ollama tag ${m.ollama_tag || m.id}`
              : warming && !serving
                ? (processAlive
                  ? "Process up — loading weights into memory…"
                  : loadPct != null
                    ? `Downloading / starting (${loadPct}%)`
                    : "Starting server…")
                : serving
                  ? (
                    `Ready — server running${server?.pid ? ` (pid ${server.pid})` : ""}`
                    + (server?.orphan ? " · leftover from earlier session" : "")
                  )
                  : processAlive
                    ? "Process up — loading weights"
                    : isActive
                      ? "Selected, not running — click Start"
                      : isCacheDiscovered(m)
                        ? cacheSourceCaption(m)
                        : "Installed, not serving";
            return (
              <div
                key={m.id}
                className={
                  "sy-settings-local-cand"
                  + (serving && isActive ? " sy-settings-local-cand--on" : "")
                  + (warming && !serving ? " sy-settings-local-cand--warm" : "")
                }
              >
                <div>
                  <strong>{m.label || m.id}</strong>
                  {serving && (
                    <span className="sy-settings-local-pill">SERVING</span>
                  )}
                  {warming && !serving && (
                    <span className="sy-settings-local-pill sy-settings-local-pill--warm">
                      STARTING
                    </span>
                  )}
                  {isActive && !serving && !warming && (
                    <span className="sy-settings-local-pill sy-settings-local-pill--idle">
                      selected
                    </span>
                  )}
                  {m.quant && <span style={{ opacity: 0.7 }}> · {m.quant}</span>}
                  {port != null && (
                    <span style={{ opacity: 0.7 }}>
                      {" "}· :{port}{serving ? " ●" : " ○"}
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 12, opacity: 0.85 }}>{statusLine}</div>
                {(warming && !serving) && (
                  <div
                    className="sy-settings-local-warm"
                    role="progressbar"
                    aria-valuemin={0}
                    aria-valuemax={100}
                    aria-valuenow={typeof loadPct === "number" ? loadPct : undefined}
                    aria-label={statusLine}
                  >
                    <div
                      className={
                        "sy-settings-local-warm-bar"
                        + (typeof loadPct === "number" ? "" : " sy-settings-local-warm-bar--indeterminate")
                      }
                      style={typeof loadPct === "number"
                        ? { width: `${Math.max(4, loadPct)}%` }
                        : undefined}
                    />
                  </div>
                )}
                <div className="sy-settings-local-cand-actions">
                  <button
                    type="button"
                    className={
                      "sy-confirm-btn"
                      + ((serving && isActive) || !isActive ? " sy-confirm-btn--primary" : "")
                    }
                    disabled={!!busy || (serving && isActive)}
                    onClick={() => void activate(m.id)}
                    title={
                      serving && isActive
                        ? "This is the active local model — ready for chat and /curate"
                        : "Make this the active local model and start its server"
                    }
                  >
                    {warming && !serving
                      ? "Starting…"
                      : serving && isActive
                        ? "In use"
                        : "Use this"}
                  </button>
                  {m.backend !== "ollama" && serving && (
                    <button
                      type="button"
                      className="sy-confirm-btn"
                      disabled={!!busy}
                      onClick={() => void controlServer(m.id, "stop")}
                      title="Stop this local server (including leftover processes from a previous session)"
                    >
                      Stop
                    </button>
                  )}
                  {m.backend !== "ollama" && (
                    <button
                      type="button"
                      className="sy-confirm-btn"
                      disabled={!!busy}
                      onClick={() => void controlServer(m.id, serving ? "restart" : "start")}
                    >
                      {warming && !serving
                        ? "Starting…"
                        : serving ? "Restart" : "Start"}
                    </button>
                  )}
                  {isCacheDiscovered(m) && !m.port ? (
                    <span
                      className="sy-settings-help"
                      title="Weights live in a shared Hugging Face cache. Switch Bay will not delete them."
                    >
                      shared cache
                    </span>
                  ) : (
                    <button
                      type="button"
                      className="sy-confirm-btn"
                      disabled={!!busy}
                      onClick={() => void removeModel(m.id)}
                    >
                      Remove
                    </button>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {backend === "mlx" && mlxSupported && !mlxInstalled && (
        <p className="sy-settings-blurb" style={{ color: "var(--type-fact)" }}>
          This Mac supports MLX, but <code>mlx-lm</code> is not on PATH.
          Install with{" "}
          <code>{backends?.mlx?.install_hint || "uv tool install mlx-lm"}</code>
          , then <code>make restart</code>.
        </p>
      )}
      {backend === "mlx" && mlxInstalled && installedForBackend.length === 0 && (
        <p className="sy-settings-blurb">
          No MLX weights on disk yet — search below, or switch to llama.cpp
          if you already installed a GGUF.
        </p>
      )}
      {backend === "mlx" && mlxInstalled && installedForBackend.length === 0 && (
        <div className="sy-settings-blurb" style={{ marginBottom: 10 }}>
          {(body?.installed || []).filter((m) => (m.backend || "llamacpp") === "llamacpp").length > 0 && (
            <button
              type="button"
              className="sy-confirm-btn sy-confirm-btn--primary"
              onClick={() => setBackend("llamacpp")}
            >
              Use installed llama.cpp models
            </button>
          )}
        </div>
      )}

      {!hfDownloads && (
        <p className="sy-settings-blurb">
          Hugging Face / remote model downloads are disabled by admin
          policy. Set <code>features.hf_model_download</code> to{" "}
          <code>true</code> in the machine admin file to allow Search
          &amp; Install. Models already on disk still work below.
        </p>
      )}

      {/* Search / install */}
      {hfDownloads && (
      <>
      <div className="sy-settings-blurb" style={{ fontWeight: 600, marginBottom: 6 }}>
        Find &amp; install
      </div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", marginBottom: 8 }}>
        <input
          type="text"
          className="sy-ws-input"
          value={query}
          placeholder={
            backend === "ollama"
              ? "qwen2.5-coder:7b"
              : backend === "mlx"
                ? "mlx-community/Qwen3-8B-4bit  (or leave blank to browse)"
                : "unsloth/Qwen3-8B-GGUF  (or leave blank to browse)"
          }
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") { e.preventDefault(); void runSearch(); }
          }}
          style={{ flex: "1 1 220px", minWidth: 180 }}
          aria-label="Model id or search"
          disabled={backend === "mlx" && !mlxInstalled}
        />
        {backend !== "ollama" && (
          <select
            value={sort}
            onChange={(e) => setSort(e.target.value as SortKey)}
            aria-label="Sort by"
            style={{ fontSize: 12 }}
            disabled={!!busy}
          >
            <option value="downloads">most downloaded</option>
            <option value="trendingScore">trending</option>
            <option value="lastModified">recently updated</option>
          </select>
        )}
        <button
          type="button"
          className="sy-confirm-btn sy-confirm-btn--primary"
          disabled={!!busy || (backend === "mlx" && !mlxInstalled)}
          onClick={() => void runSearch()}
        >
          {busy === "search" ? "Searching…" : "Search"}
        </button>
      </div>

      {searchNote && (
        <p className="sy-settings-blurb" style={{ marginTop: 0 }}>{searchNote}</p>
      )}

      {hits && hits.length > 0 && (
        <div style={{ marginBottom: 10 }}>
          {hits.map((h) => (
            <div key={h.repo + (h._tier || "")} className="sy-settings-local-cand">
              <div>
                <strong>{h.repo}</strong>
                {h._tier === "exact" && (
                  <span style={{ marginLeft: 6, fontSize: 11, fontWeight: 600, color: "var(--accent)" }}>
                    exact
                  </span>
                )}
                {h._tier === "alt" && (
                  <span style={{ marginLeft: 6, fontSize: 11, opacity: 0.75 }}>
                    alternative
                  </span>
                )}
                {h.trusted && (
                  <span style={{ marginLeft: 6, fontSize: 11, opacity: 0.8 }}>
                    · known publisher
                  </span>
                )}
                {h.off_task && (
                  <span style={{ marginLeft: 6, fontSize: 11, opacity: 0.8 }}>
                    · roleplay finetune
                  </span>
                )}
              </div>
              {backend !== "ollama" && (
                <div style={{ fontSize: 12, opacity: 0.85 }}>
                  {typeof h.downloads === "number" ? `${h.downloads.toLocaleString()} downloads` : ""}
                  {typeof h.likes === "number" ? ` · ${h.likes} likes` : ""}
                  {h.last_modified ? ` · updated ${String(h.last_modified).slice(0, 10)}` : ""}
                </div>
              )}
              <div className="sy-settings-local-cand-actions">
                <button
                  type="button"
                  className="sy-confirm-btn sy-confirm-btn--primary"
                  disabled={!!busy || inst?.state === "running"}
                  onClick={() => void installHit(h)}
                >
                  {busy === "install" ? "Starting…"
                    : backend === "ollama" ? "Pull with Ollama" : "Install"}
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      {inst?.state === "running" && (
        <div className="sy-settings-blurb" style={{ marginBottom: 10 }}>
          <div>
            Installing — {inst.step}
            {typeof inst.percent === "number" ? ` (${inst.percent}%)` : ""}
          </div>
          <div
            style={{
              marginTop: 6, height: 6, borderRadius: 99,
              background: "var(--line)", overflow: "hidden",
            }}
          >
            <div
              style={{
                height: "100%", width: `${Math.max(2, inst.percent ?? 0)}%`,
                background: "var(--accent)", transition: "width 0.4s ease",
              }}
            />
          </div>
        </div>
      )}
      {inst?.state === "error" && inst.error && (
        <p className="sy-settings-status sy-settings-status--err">{inst.error}</p>
      )}
      </>
      )}

      {/* Active server controls (current backend) */}
      {config && activeBackend === backend && (
        <div style={{ marginTop: 8, marginBottom: 8 }}>
          <p className="sy-settings-blurb">
            {body.server_healthy ? "Serving" : "Selected"}:{" "}
            <strong>{config.model_label}</strong>
            {config.quant ? ` (${config.quant}, ` : " ("}
            {Math.round((config.ctx ?? 0) / 1024)}k context)
            {body.server_healthy
              ? (config.port != null ? ` on :${config.port}` : "")
              : " — not running (use Start)"}
            {body.server_url && body.server_healthy ? ` ${body.server_url}` : ""}
          </p>
          <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
            <button
              type="button"
              className="sy-confirm-btn"
              onClick={() => void watch(body.active || config?.candidate_id)}
              title={
                activeBackend === "mlx"
                  ? "Open a terminal tailing the MLX server log"
                  : "Open a terminal tailing the llama-server log"
              }
            >
              Watch server
            </button>
            <label
              style={{ fontSize: 12, display: "flex", alignItems: "center", gap: 5 }}
              title="Off (recommended) makes the small model act directly; on lets it think first"
            >
              <input
                type="checkbox"
                checked={!!config.reasoning}
                onChange={(e) => void toggleReasoning(e.target.checked)}
              />
              model reasoning
            </label>
          </div>
        </div>
      )}

      {err && <p className="sy-settings-status sy-settings-status--err">{err}</p>}
      {note && !err && <p className="sy-settings-status">{note}</p>}

      {harness && (
        <details className="sy-harness">
          <summary className="sy-harness-summary">
            Model harness (advanced)
            <span className="sy-harness-meta">
              {harness.lines} lines · refines &gt; {harness.refine_lines}
            </span>
          </summary>
          <p className="sy-settings-blurb" style={{ marginTop: 6 }}>
            Operating rules appended to the system prompt for local models.
            Edit here or in <code>{harness.path}</code>.
          </p>
          <textarea
            className="sy-harness-text"
            value={harnessDraft}
            spellCheck={false}
            onChange={(e) => setHarnessDraft(e.target.value)}
          />
          <div style={{ display: "flex", gap: 8, alignItems: "center", marginTop: 6 }}>
            <button
              type="button"
              className="sy-confirm-btn sy-confirm-btn--primary"
              onClick={() => void saveHarness()}
              disabled={harnessDraft.trim() === harness.text.trim() || !harnessDraft.trim()}
            >
              Save harness
            </button>
            <button
              type="button"
              className="sy-confirm-btn"
              onClick={() => setHarnessDraft(harness.text)}
              disabled={harnessDraft === harness.text}
            >
              Revert
            </button>
            {harnessSaved && <span className="sy-settings-blurb" style={{ margin: 0 }}>saved ✓</span>}
          </div>
        </details>
      )}
    </section>
  );
}


// ── Workspaces home panel (stage 5, D2 detail ruling) ──────────────
// The fixed directory where NEW workspaces born inside switchbay
// (merge results, split-offs) land, plus a migrate affordance for
// existing workspaces scattered elsewhere. The one real user
// decision is cloud tracking: point it at ~/Documents/Workspaces
// (or a Dropbox/Drive path) to make workspaces roam.

type WorkspacesHomeBody = {
  home: string;
  expanded: string;
  exists: boolean;
  candidates: { path: string; name: string }[];
  active: string;
};

function WorkspacesHomePanel({ open }: { open: boolean }) {
  const [body, setBody] = useState<WorkspacesHomeBody | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  // After a verified copy, the source folder is RETAINED until the
  // user confirms removal (two-phase move). Holds the {old,new} pair.
  const [pendingCleanup, setPendingCleanup] =
    useState<{ old: string; new: string; kept?: number } | null>(null);

  useEffect(() => {
    if (!open) return;
    void (async () => {
      try {
        const r = await fetch("/api/workspaces/home");
        if (!r.ok) return;
        const b = (await r.json()) as WorkspacesHomeBody;
        setBody(b);
        setDraft(b.home);
        setStatus(null);
      } catch { /* older daemon — panel stays hidden */ }
    })();
  }, [open]);

  const saveHome = async () => {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      const r = await fetch("/api/workspaces/home", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ home: draft }),
      });
      const b = await r.json().catch(() => ({} as Record<string, unknown>));
      if (!r.ok) {
        setStatus({ ok: false, msg: String((b as { error?: string }).error ?? r.status) });
        return;
      }
      setBody(b as WorkspacesHomeBody);
      setDraft((b as WorkspacesHomeBody).home);
      setStatus({ ok: true, msg: "saved — new merges/splits will land here" });
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const migrate = async (path: string) => {
    if (busy) return;
    if (!window.confirm(
      `Copy ${path} into ${body?.expanded}?\n\nThe durable content is copied (regenerable caches like .venv / uv-cache are skipped) and verified; the registry + machine-local state repoint to the new location. Environment + graph then rebuild in the background so edges work without a manual setup. The ORIGINAL folder is left in place — you'll be asked whether to delete it once the copy is confirmed.`,
    )) return;
    setBusy(true);
    setStatus(null);
    setPendingCleanup(null);
    try {
      const r = await fetch("/api/workspaces/migrate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path }),
      });
      const b = await r.json().catch(() => ({} as Record<string, unknown>));
      if (!r.ok) {
        setStatus({ ok: false, msg: String((b as { error?: string }).error ?? r.status) });
        return;
      }
      setBody(b as WorkspacesHomeBody);
      const m = (b as {
        migrated?: {
          old: string;
          new: string;
          kept?: number;
          env_rebuild?: string;
        };
      }).migrated;
      if (m) {
        setPendingCleanup({ old: m.old, new: m.new, kept: m.kept });
        const envNote =
          (m as { env_rebuild?: string }).env_rebuild === "started"
            ? " Rebuilding environment + graph in the background (rail will report when ready)."
            : "";
        setStatus({
          ok: true,
          msg: `copied ${m.kept ?? ""} files → ${m.new}.${envNote} Original kept — remove it below when ready.`,
        });
      } else {
        setStatus({ ok: true, msg: "copied" });
      }
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const removeOldCopy = async () => {
    if (busy || !pendingCleanup) return;
    const { old, new: neu } = pendingCleanup;
    if (!window.confirm(`Permanently delete the old copy at\n${old}?`)) return;
    setBusy(true);
    try {
      const r = await fetch("/api/workspaces/migrate/cleanup", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ old, new: neu }),
      });
      const b = await r.json().catch(() => ({} as Record<string, unknown>));
      if (!r.ok) {
        setStatus({ ok: false, msg: String((b as { error?: string }).error ?? r.status) });
        return;
      }
      setBody(b as WorkspacesHomeBody);
      setPendingCleanup(null);
      setStatus({ ok: true, msg: "old copy removed — move complete" });
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  if (body === null) return null;
  const dirty = draft !== body.home;

  return (
    <section className="sy-settings-packs">
      <h3 className="sy-settings-h3">Workspaces home</h3>
      <p className="sy-settings-blurb">
        Where workspaces created inside Switch Bay (merge results,
        split-offs) land. Keep it local (default <code>~/Workspaces</code>)
        for speed, or point it somewhere cloud-tracked like{" "}
        <code>~/Documents/Workspaces</code> if you want workspaces to roam
        with a sync service.
      </p>
      <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
        <input
          type="text"
          className="sy-settings-input"
          style={{ flex: 1, fontFamily: "ui-monospace, Menlo, monospace", fontSize: 11 }}
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          spellCheck={false}
        />
        <button
          type="button"
          className="sy-settings-pill"
          disabled={busy || !dirty}
          onClick={() => void saveHome()}
        >
          Save
        </button>
      </div>
      {body.candidates.length > 0 && (
        <>
          <p className="sy-settings-blurb" style={{ marginTop: 10 }}>
            Registered workspaces outside the home — move them in
            (folder + registry + local state; the active workspace can't
            move while it's being served):
          </p>
          {body.candidates.map((c) => (
            <div key={c.path} style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
              <code style={{ flex: 1, minWidth: 0, overflowWrap: "anywhere", wordBreak: "break-all", fontSize: 11 }}>
                {c.path}
              </code>
              <button
                type="button"
                className="sy-settings-pill"
                style={{ flexShrink: 0, whiteSpace: "nowrap" }}
                disabled={busy}
                onClick={() => void migrate(c.path)}
              >
                → move into home
              </button>
            </div>
          ))}
        </>
      )}
      {pendingCleanup && (
        <div
          style={{
            display: "flex", alignItems: "center", gap: 8, marginTop: 10,
            padding: "8px 10px", borderRadius: 6,
            border: "1px solid var(--border)", background: "var(--bg-elev)",
          }}
        >
          <span style={{ flex: 1, minWidth: 0, fontSize: 11, overflowWrap: "anywhere", wordBreak: "break-all" }}>
            Copy verified. Old copy still at{" "}
            <code>{pendingCleanup.old}</code>.
          </span>
          <button
            type="button"
            className="sy-settings-pill"
            style={{ flexShrink: 0, whiteSpace: "nowrap" }}
            disabled={busy}
            onClick={() => void removeOldCopy()}
            title="Permanently delete the original folder"
          >
            Remove old copy
          </button>
          <button
            type="button"
            className="sy-settings-pill"
            style={{ flexShrink: 0, whiteSpace: "nowrap" }}
            disabled={busy}
            onClick={() => { setPendingCleanup(null); setStatus(null); }}
            title="Leave the original in place; you can delete it yourself later"
          >
            Keep both
          </button>
        </div>
      )}
      {status && (
        <p className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}>
          {status.msg}
        </p>
      )}
    </section>
  );
}


// ── Curator profile panel (D6) ─────────────────────────────────────
// Per-workspace, user-editable steering for the curator — e.g. "SKUs
// like AB-1234 are always entities". Persisted to the workspace's
// .curator/profile.md (roams + survives merges/splits); injected
// verbatim (capped) into curate prompts. Complements the CE skill,
// never modifies it.

type CuratorProfileBody = { profile: string; cap: number; workspace_name: string };

// Greyed-out structure template — teaches the shape (and the
// anti-patterns away) without docs. Every section is a kind of RULING
// the generic skill can't derive.
const CURATOR_PLACEHOLDER = `One line: what this workspace is about (doubles as the routing description).

Entity rulings, with the why — what ALWAYS gets a page:
e.g. project IDs like PROJ-1234 always link to their project definition page.
…and what never does (e.g. organizations, one-off vendors).

Concept / fact standards — what a fact must carry to be worth keeping.

Scope edges — adjacent material that IS in scope, and where to route it.

Noise — what looks like content here but should be skipped.`;

function CuratorPanel({ open }: { open: boolean }) {
  const [body, setBody] = useState<CuratorProfileBody | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  // "Draft it for me": run id of the background drafting agent; while
  // set, the panel polls the GET until the file changes.
  const [draftRun, setDraftRun] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    void (async () => {
      try {
        const r = await fetch("/api/curator-profile");
        if (!r.ok) return;
        const b = (await r.json()) as CuratorProfileBody;
        setBody(b);
        setDraft(b.profile);
        setStatus(null);
      } catch { /* older daemon — panel stays hidden */ }
    })();
  }, [open]);

  const draftForMe = async () => {
    if (busy || draftRun) return;
    setStatus(null);
    try {
      const r = await fetch("/api/curator-profile/draft", { method: "POST" });
      if (!r.ok) {
        const b = await r.json().catch(() => ({} as Record<string, string>));
        setStatus({ ok: false, msg: b.error || `HTTP ${r.status}` });
        return;
      }
      const b = (await r.json()) as { run_id: string };
      setDraftRun(b.run_id);
      setStatus({
        ok: true,
        msg: "Drafting in the background — the agent surveys the wiki and writes the profile "
          + "(watch the Agents panel; approve its Write if asked). It will appear here when done.",
      });
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    }
  };

  // Poll while a draft run is out. Never clobber the user's unsaved
  // edits: only auto-load when the box still matches the saved text.
  useEffect(() => {
    if (!draftRun || !open) return;
    let polls = 0;
    const iv = setInterval(async () => {
      polls += 1;
      if (polls > 60) { // ~4 min — give up quietly, reopen refetches
        setDraftRun(null);
        return;
      }
      try {
        const r = await fetch("/api/curator-profile");
        if (!r.ok) return;
        const b = (await r.json()) as CuratorProfileBody;
        if (b.profile && body !== null && b.profile !== body.profile) {
          setBody(b);
          setDraft((cur) => (cur === body.profile ? b.profile : cur));
          setDraftRun(null);
          setStatus({ ok: true, msg: "Draft loaded — review, edit, and it's live (the agent already saved it)." });
        }
      } catch { /* transient — next tick */ }
    }, 4000);
    return () => clearInterval(iv);
  }, [draftRun, open, body]);

  const save = async () => {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      const r = await fetch("/api/curator-profile", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile: draft }),
      });
      if (!r.ok) {
        const b = await r.json().catch(() => ({} as Record<string, string>));
        setStatus({ ok: false, msg: b.error || `HTTP ${r.status}` });
        return;
      }
      const b = (await r.json()) as CuratorProfileBody;
      setBody(b);
      setDraft(b.profile);
      setStatus({ ok: true, msg: "Saved to .curator/profile.md" });
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  if (body === null) return null;
  const dirty = draft !== body.profile;
  // The cap is measured in estimated tokens (server uses the same
  // chars/4 approximation), 2.5k per the 2026-07-05 ruling.
  const estTokens = Math.ceil(draft.length / 4);
  const overCap = estTokens > body.cap;
  const firstLine = draft.split("\n").find((l) => l.trim())?.trim() ?? "";

  return (
    <section className="sy-settings-packs">
      <h3 className="sy-settings-h3">Curator profile · {body.workspace_name}</h3>
      <p className="sy-settings-blurb">
        Tells the curator the per-project and domain nuances it can't
        infer from the generic skill — most usefully, that certain
        kinds of information should <em>always</em> be treated a
        certain way. Example: “project IDs like <code>PROJ-1234</code>{" "}
        always get linked to their project definition page”, or
        “catalog codes like <code>AB-1234</code> always get an entity
        page”. What works: state <strong>rulings, not vibes</strong>;
        give the <strong>why</strong> so the curator can generalize;
        include the negative edge too (what should <em>not</em> get a
        page); leave file naming / frontmatter mechanics to the skill.
        The profile is injected verbatim into every curate pass.
      </p>
      <textarea
        className="sy-settings-textarea"
        rows={9}
        value={draft}
        onChange={(ev) => setDraft(ev.target.value)}
        placeholder={CURATOR_PLACEHOLDER}
        spellCheck={false}
      />
      <p className="sy-settings-blurb sy-settings-firstline" title="Comms-stream triage judges message relevance against this line — name the domains plainly.">
        <strong>line 1 → routing description:</strong>{" "}
        {firstLine
          ? <code>{firstLine.length > 90 ? firstLine.slice(0, 90) + "…" : firstLine}</code>
          : <em>(empty — comms routing will only see the workspace folder name)</em>}
      </p>
      <div className="sy-settings-perm-row">
        <span className="sy-settings-blurb" style={{ margin: 0, fontSize: "0.85em" }}>
          ~{estTokens} tokens
          {overCap ? (
            <>
              {" "}— only the first <strong>~{body.cap}</strong> are
              injected into prompts (the full text is saved)
            </>
          ) : (
            <> (cap ~{body.cap})</>
          )}
        </span>
        <span className="sy-spacer" />
        <button
          type="button"
          className="sy-settings-pill"
          onClick={() => void draftForMe()}
          disabled={busy || draftRun !== null}
          title="A background agent surveys the wiki (projects, buckets, sample pages) and drafts the profile; existing rulings are preserved"
        >
          {draftRun ? "drafting…" : "draft it for me"}
        </button>
        <button
          type="button"
          className="sy-settings-pill"
          onClick={() => void save()}
          disabled={busy || !dirty}
        >
          {busy ? "saving…" : dirty ? "save" : "saved"}
        </button>
      </div>
      {status && (
        <p className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}>
          {status.msg}
        </p>
      )}
    </section>
  );
}


function StoragePanel({ open }: { open: boolean }) {
  const [settings, setSettings] = useState<SettingsBody | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  const reload = async () => {
    try {
      const r = await fetch("/api/settings");
      if (!r.ok) return;
      setSettings((await r.json()) as SettingsBody);
    } catch {
      /* older daemon without /api/settings — panel stays hidden */
    }
  };

  useEffect(() => {
    if (!open) return;
    void reload();
  }, [open]);

  const toggleLocal = async () => {
    if (!settings || busy) return;
    const next = !settings.rail_history_local;
    setBusy(true);
    setStatus(null);
    try {
      const r = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rail_history_local: next }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({} as Record<string, string>));
        setStatus({ ok: false, msg: body.error || `HTTP ${r.status}` });
        return;
      }
      setSettings((await r.json()) as SettingsBody);
      setStatus({
        ok: true,
        msg: next
          ? "Rail history is now machine-local — moved out of the workspace."
          : "Rail history now roams with the workspace.",
      });
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const setEmbeddingBackend = async (backend: string) => {
    if (!settings || busy) return;
    setBusy(true);
    setStatus(null);
    try {
      const r = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ embedding_backend: backend }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({} as Record<string, string>));
        setStatus({ ok: false, msg: body.error || `HTTP ${r.status}` });
        return;
      }
      setSettings((await r.json()) as SettingsBody);
      setStatus({
        ok: true,
        msg: backend === "auto"
          ? "Embeddings run locally (nothing leaves this machine)."
          : `Embeddings now go to ${backend} — rail text is sent to that provider.`,
      });
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  // Don't render until we know the daemon supports the endpoint.
  if (settings === null) return null;

  return (
    <section className="sy-settings-packs">
      <h3 className="sy-settings-h3">Storage</h3>
      <p className="sy-settings-blurb">
        Switch Bay keeps machine-local, regenerable state (fan-out runs,
        the curation cache) off cloud-sync services automatically, so a
        workspace under iCloud / OneDrive / Dropbox stays fast and can't
        wedge the daemon. The one user-facing choice is where rail chat
        history lives.
        {settings.workspace_synced && (
          <>
            {" "}This workspace appears to be on{" "}
            <strong>{settings.workspace_synced}</strong>.
          </>
        )}
      </p>
      <div className="sy-settings-perm-row">
        <span>
          <strong>Rail history:</strong>{" "}
          {settings.rail_history_local
            ? "machine-local (default — fast, does not roam)"
            : "roams with the workspace"}
        </span>
        <span className="sy-spacer" />
        <button
          type="button"
          className={
            "sy-settings-pill"
            + (settings.rail_history_local ? " sy-settings-pill--on" : "")
          }
          onClick={() => void toggleLocal()}
          disabled={busy}
          title={
            settings.rail_history_local
              ? "Click to let rail history roam across machines via the workspace's sync service"
              : "Click to keep rail history on this machine only (faster + sync-corruption-safe)"
          }
        >
          {settings.rail_history_local ? "local" : "roams"}
        </button>
      </div>
      <p className="sy-settings-blurb" style={{ marginTop: 8, fontSize: "0.85em" }}>
        <code>{settings.rail_history_path}</code>
      </p>
      <p className="sy-settings-blurb" style={{ marginTop: 4 }}>
        Roaming follows you between machines but puts a live SQLite file
        on the sync service, which can corrupt under concurrent edits.
        Machine-local avoids that at the cost of per-machine history.
      </p>

      <h4 className="sy-settings-h4" style={{ marginTop: 22 }}>
        Semantic recall (conversation memory)
      </h4>
      <p className="sy-settings-blurb">
        The rail can look back through your past chats by <em>meaning</em>,
        not just exact words — so asking “what did we decide about the API?”
        surfaces the relevant earlier messages even if you phrased them
        differently at the time. To do that it needs an{" "}
        <strong>embedding model</strong>: a small model that turns each
        message into a numeric vector so related ones can be found. This is
        separate from — and doesn’t change — which model you actually chat
        with; it only powers recall. Choose where it runs:
      </p>
      <div className="sy-settings-perm-row" style={{ marginTop: 8 }}>
        <span>
          <strong>Embedding model:</strong>{" "}
          {settings.embedding_backend === "auto"
            ? "on-device (nothing leaves this machine)"
            : `${settings.embedding_backend} API — text sent to the provider`}
        </span>
        <span className="sy-spacer" />
        <select
          className="sy-settings-select"
          value={settings.embedding_backend ?? "auto"}
          disabled={busy}
          onChange={(e) => void setEmbeddingBackend(e.target.value)}
          title="Which model computes embeddings for semantic recall"
        >
          <option value="auto">Local (fastembed / on-device)</option>
          {Object.entries(settings.embedding_vendors_keyed ?? {}).map(([id, keyed]) => (
            <option key={id} value={id} disabled={!keyed}>
              {id} API{keyed ? "" : " (add a key first)"}
            </option>
          ))}
        </select>
      </div>
      <p className="sy-settings-blurb" style={{ marginTop: 6, fontSize: "0.85em" }}>
        <strong>Local</strong> (default) runs on your machine and keeps chat
        text private — it needs the <code>fastembed</code> (or PyTorch) extra
        installed; without it, recall quietly falls back to plain keyword
        search. <strong>OpenAI</strong> and <strong>Gemini</strong> are the
        only providers with an embeddings API we wire in — picking one needs
        no local setup but <strong>sends your rail text to that provider</strong>.
        Switching re-embeds your existing history in the background.
      </p>

      {status && (
        <p className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}>
          {status.msg}
        </p>
      )}
    </section>
  );
}


/** Image / video / voice generation prefs (xAI Imagine+Voice, OpenAI
 *  images/Sora/TTS/Realtime). Prefs only — rail tools that write
 *  figures, sketch assets, or HTML embeds will read these later. */
function MediaPanel({ open }: { open: boolean }) {
  const [settings, setSettings] = useState<SettingsBody | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  const reload = async () => {
    try {
      const r = await fetch("/api/settings");
      if (!r.ok) return;
      setSettings((await r.json()) as SettingsBody);
    } catch {
      /* older daemon */
    }
  };

  useEffect(() => {
    if (!open) return;
    void reload();
  }, [open]);

  const saveModality = async (
    modality: string,
    provider: string,
    model: string,
  ) => {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      const payload =
        !provider
          ? { [modality]: null }
          : { [modality]: { provider, model } };
      const r = await fetch("/api/settings", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ media: payload }),
      });
      if (!r.ok) {
        const body = await r.json().catch(() => ({} as { error?: string }));
        setStatus({ ok: false, msg: body.error || `HTTP ${r.status}` });
        return;
      }
      setSettings((await r.json()) as SettingsBody);
      setStatus({
        ok: true,
        msg: !provider
          ? `${modality} unset — no auto media calls`
          : `${modality} → ${provider} / ${model}`,
      });
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  if (!settings?.media?.modalities) return null;
  const mods = settings.media.modalities;
  const order = ["image", "video", "voice"] as const;

  return (
    <section className="sy-settings-packs">
      <h3 className="sy-settings-h3">Media generation</h3>
      <p className="sy-settings-blurb">
        Pick provider + model for image, video, and voice when a supporting
        API key is set (xAI Grok Imagine / Voice, OpenAI images · Sora · TTS ·
        Realtime). These are <strong>preferences only</strong> for now —
        rail tools that place images on sketch slides, store figures from
        docs, or embed video in HTML artifacts will use them. Unset =
        switchbay will not call paid media APIs on its own.
      </p>
      {order.map((modality) => {
        const state = mods[modality];
        if (!state) return null;
        const choice = state.choice;
        const providerId = choice?.provider ?? "";
        const provider = state.providers.find((p) => p.id === providerId);
        const modelOpts = provider?.models ?? [];
        const modelId = choice?.model && modelOpts.includes(choice.model)
          ? choice.model
          : (choice?.model || provider?.default_model || "");
        const anyKey = state.providers.some((p) => p.has_key);
        return (
          <div key={modality} className="sy-settings-ladder-row" style={{ marginBottom: 10 }}>
            <span className="sy-settings-ladder-label" style={{ textTransform: "capitalize" }}>
              {modality}
            </span>
            <select
              className="sy-settings-input"
              disabled={busy || !anyKey}
              value={providerId}
              onChange={(e) => {
                const pid = e.target.value;
                if (!pid) {
                  void saveModality(modality, "", "");
                  return;
                }
                const p = state.providers.find((x) => x.id === pid);
                const mid = p?.default_model || p?.models[0] || "";
                void saveModality(modality, pid, mid);
              }}
              title={state.blurb}
              aria-label={`${modality} provider`}
            >
              <option value="">
                {anyKey ? "(unset)" : "(add an xAI or OpenAI key)"}
              </option>
              {state.providers.map((p) => (
                <option key={p.id} value={p.id} disabled={!p.has_key}>
                  {p.label}{p.has_key ? "" : " (no key)"}
                </option>
              ))}
            </select>
            <select
              className="sy-settings-input"
              disabled={busy || !providerId}
              value={modelId}
              onChange={(e) => {
                if (!providerId) return;
                void saveModality(modality, providerId, e.target.value);
              }}
              aria-label={`${modality} model`}
            >
              {!providerId && <option value="">(pick provider)</option>}
              {providerId && modelOpts.length === 0 && (
                <option value="">(no models listed)</option>
              )}
              {modelOpts.map((m) => (
                <option key={m} value={m}>{m}</option>
              ))}
              {choice?.model && !modelOpts.includes(choice.model) && (
                <option value={choice.model}>{choice.model}</option>
              )}
            </select>
          </div>
        );
      })}
      {settings.media.note && (
        <p className="sy-settings-blurb" style={{ fontSize: "0.85em", marginTop: 4 }}>
          {settings.media.note}
        </p>
      )}
      {status && (
        <p className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}>
          {status.msg}
        </p>
      )}
    </section>
  );
}


type StreamAccount = {
  id: string;
  provider: string;
  label: string;
  identity: string | null;
  status: string;
  pending: number;
  auto_curate: boolean;
  last_poll: number | null;
  tenant?: string;
  workspace: string;
  triage?: boolean;
  routing?: "default" | "smart" | "fanout";
  /** Effective target allowlist — the only routing authority. */
  workspaces?: string[];
};

type StreamsBody = {
  accounts: StreamAccount[];
  providers: Record<string, {
    label: string;
    needs_secret: boolean;
    auth: "oauth" | "password";
    fields: { key: string; label: string; secret: boolean; required: boolean }[];
    setup_help: string;
  }>;
  redirect_uri: string;
  workspaces: { path: string; name: string }[];
};

// ── Watch folders panel (D5) ────────────────────────────────────────
// Auto-ingest NEW files from user-chosen external directories. Adding
// a folder baselines its current contents (only files arriving after
// that point ingest); each new file dispatches one background ingest
// agent, capped per beat so a folder-dump can't stampede.

type WatchFolder = { path: string; enabled: boolean; added_at: number };

function WatchFoldersPanel({ open }: { open: boolean }) {
  const [folders, setFolders] = useState<WatchFolder[] | null>(null);
  const [meta, setMeta] = useState<{ cap: number; interval: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  useEffect(() => {
    if (!open) return;
    void (async () => {
      try {
        const r = await fetch("/api/watch-folders");
        if (!r.ok) return;
        const b = (await r.json()) as {
          folders: WatchFolder[]; cap_per_beat: number; interval_s: number;
        };
        setFolders(b.folders);
        setMeta({ cap: b.cap_per_beat, interval: b.interval_s });
        setStatus(null);
      } catch { /* older daemon — panel stays hidden */ }
    })();
  }, [open]);

  const call = async (
    route: string,
    body: Record<string, unknown>,
    okMsg?: string,
  ) => {
    if (busy) return;
    setBusy(true);
    setStatus(null);
    try {
      const r = await fetch(`/api/watch-folders/${route}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const b = await r.json().catch(() => ({} as Record<string, unknown>));
      if (!r.ok) {
        setStatus({ ok: false, msg: String(b.error ?? `HTTP ${r.status}`) });
        return;
      }
      if ((b as { cancelled?: boolean }).cancelled) return;
      if (Array.isArray((b as { folders?: WatchFolder[] }).folders)) {
        setFolders((b as { folders: WatchFolder[] }).folders);
      }
      if (okMsg) setStatus({ ok: true, msg: okMsg });
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  if (folders === null) return null;

  return (
    <section className="sy-settings-packs">
      <h3 className="sy-settings-h3">Watch folders</h3>
      <p className="sy-settings-blurb">
        Folders Switch Bay keeps an eye on: any <em>new</em> file that
        appears gets staged into the vault and a background ingest agent
        extracts a wiki page, with provenance pointing at the original
        (see the Browser's Sources view). Existing contents are left
        alone when you add a folder — this is a tap on the shoulder for
        new material, not a bulk import
        {meta ? ` (checked ~every ${meta.interval}s, at most ${meta.cap} files per check)` : ""}.
      </p>
      {folders.length === 0 && (
        <p className="sy-settings-blurb" style={{ opacity: 0.75 }}>
          No folders watched yet — try your downloads or a notes-export
          directory.
        </p>
      )}
      {folders.map((f) => (
        <div key={f.path} className="sy-settings-pill-row" style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
          <code style={{ flex: 1, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", fontSize: 11 }} title={f.path}>
            {f.path}
          </code>
          <button
            type="button"
            className={"sy-settings-pill" + (f.enabled ? " sy-settings-pill--on" : "")}
            disabled={busy}
            onClick={() => void call("toggle", { path: f.path, enabled: !f.enabled }, f.enabled ? "paused (re-enabling re-baselines — files added while paused won't ingest)" : "watching")}
            title={f.enabled
              ? "Pause watching (files that arrive while paused are skipped)"
              : "Resume watching from now"}
          >
            {f.enabled ? "watching" : "paused"}
          </button>
          <button
            type="button"
            className="sy-settings-pill"
            disabled={busy}
            onClick={() => void call("remove", { path: f.path }, "removed")}
            title="Stop watching this folder (already-ingested pages stay)"
          >
            ✕
          </button>
        </div>
      ))}
      <button
        type="button"
        className="sy-settings-pill"
        disabled={busy}
        onClick={() => void call("add", { pick: true }, "added — new files from now on will auto-ingest")}
        title="Choose a folder with the OS picker"
      >
        + Add folder…
      </button>
      {status && (
        <p className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}>
          {status.msg}
        </p>
      )}
    </section>
  );
}


/** Comms streams: connect Gmail / Outlook+Teams / Slack as CURATION
 *  SOURCES. Browser-based OAuth with a loopback redirect; the user
 *  (or their org) supplies the app's client id, so consent stays
 *  under enterprise control. Messages land in a machine-local
 *  transit buffer and are deleted after each curation pass — the
 *  wiki keeps knowledge + deep links, never the mail archive. */
function StreamsPanel({ open }: { open: boolean }) {
  const [body, setBody] = useState<StreamsBody | null>(null);
  const [prov, setProv] = useState("imap");
  const [form, setForm] = useState({ label: "", client_id: "", client_secret: "", tenant: "" });
  // Password-tier credentials are provider-declared fields, rendered
  // generically — adding a channel adapter server-side needs no UI edit.
  const [fieldVals, setFieldVals] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);
  const [confirmRemove, setConfirmRemove] = useState<string | null>(null);

  const refresh = async () => {
    try {
      const r = await fetch("/api/streams");
      if (r.ok) setBody(await r.json() as StreamsBody);
    } catch { /* older daemon */ }
  };
  useEffect(() => { if (open) void refresh(); }, [open]);

  if (!open || body === null) return null;
  const pinfo = body.providers[prov];

  const call = async (label: string, path: string, init?: RequestInit) => {
    setBusy(label);
    setStatus(null);
    try {
      const r = await fetch(path, init);
      const b = await r.json().catch(() => ({} as Record<string, unknown>));
      if (!r.ok) {
        setStatus({ ok: false, msg: String((b as { error?: string }).error || `HTTP ${r.status}`) });
        return null;
      }
      return b as Record<string, unknown>;
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
      return null;
    } finally {
      setBusy(null);
      void refresh();
    }
  };

  const add = async () => {
    const isPw = body?.providers[prov]?.auth === "password";
    const b = await call("add", "/api/streams/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider: prov, ...form, fields: fieldVals }),
    });
    if (b) {
      setForm({ label: "", client_id: "", client_secret: "", tenant: "" });
      setFieldVals({});
      setStatus({
        ok: true,
        msg: isPw
          ? "Connected — credentials verified. Poll now to capture the first batch."
          : "Account added — now click Connect to log in via your browser.",
      });
    }
  };

  const connect = async (id: string) => {
    const b = await call("connect", `/api/streams/${id}/login`);
    const url = b && typeof b.auth_url === "string" ? b.auth_url : null;
    if (url) window.open(url, "_blank", "noopener");
  };

  return (
    <section className="sy-settings-packs">
      <h3 className="sy-settings-h3">Comms streams</h3>
      <p className="sy-settings-blurb">
        Connect email / chat streams as <strong>curation sources</strong>:
        new messages are captured to a machine-local transit buffer,
        a curation pass extracts durable knowledge into the wiki with
        deep-links back to the source, and the buffer is then deleted —
        conversations are never archived here. Two ways in:{" "}
        <strong>Email (IMAP)</strong> is the simple path — any mail
        provider, just your address + an app password, nothing to
        register. The <strong>OAuth</strong> providers are the
        enterprise path: login happens in your browser on the
        provider's own pages (OAuth + PKCE, loopback redirect) against
        your own app registration, so consent, scopes and tenant
        policy stay under your (or your org's) control.
      </p>
      {body.accounts.map((a) => (
        <div key={a.id} className="sy-settings-perm-row" style={{ flexWrap: "wrap", gap: 6 }}>
          <strong>{a.label}</strong>
          <span className="sy-purge-chip">{body.providers[a.provider]?.label ?? a.provider}</span>
          <span className="sy-purge-meta">
            {a.status === "connected"
              ? (a.identity || "connected")
              : "not connected"}
            {a.pending > 0 && ` · ${a.pending} pending`}
            {a.last_poll ? ` · polled ${new Date(a.last_poll * 1000).toLocaleTimeString()}` : ""}
          </span>
          <span className="sy-spacer" />
          {a.status !== "connected" && (
            <button type="button" className="sy-confirm-btn" disabled={busy !== null}
              onClick={() => void connect(a.id)}>
              Connect
            </button>
          )}
          {a.status === "connected" && (
            <>
              <button type="button" className="sy-confirm-btn" disabled={busy !== null}
                onClick={() => void call("poll", `/api/streams/${a.id}/poll`, { method: "POST" })
                  .then((b) => b && setStatus({ ok: true, msg: `Polled — ${String(b.new)} new, ${String(b.pending)} pending.` }))}>
                {busy === "poll" ? "Polling…" : "Poll now"}
              </button>
              <button type="button" className="sy-confirm-btn"
                disabled={busy !== null || a.pending === 0}
                title="Run the curation pass over pending messages (triage first when smart routing is on)"
                onClick={() => void call("curate", `/api/streams/${a.id}/curate`, { method: "POST" })
                  .then((b) => b && setStatus({
                    ok: true,
                    msg: `Curated ${String(b.curated)} message${b.curated === 1 ? "" : "s"}`
                      + (Array.isArray(b.workspaces) && b.workspaces.length
                        ? ` into ${(b.workspaces as string[]).join(", ")}` : "")
                      + (Number(b.skipped) > 0 ? `; ${String(b.skipped)} skipped as irrelevant` : "")
                      + ".",
                  }))}>
                {busy === "curate" ? "Curating…" : "Curate now"}
              </button>
              <button type="button"
                className={"sy-settings-pill" + (a.auto_curate ? " sy-settings-pill--on" : "")}
                title="Automatically curate after each poll cycle"
                disabled={busy !== null}
                onClick={() => void call("auto", `/api/streams/${a.id}/auto`, {
                  method: "POST",
                  headers: { "Content-Type": "application/json" },
                  body: JSON.stringify({ auto_curate: !a.auto_curate }),
                })}>
                {a.auto_curate ? "auto" : "manual"}
              </button>
              <button type="button"
                className={"sy-settings-pill"
                  + ((a.routing === "smart" || a.triage) ? " sy-settings-pill--on" : "")}
                title={"Gate mode — click to toggle. smart gate: one cheap per-workspace keep/skip "
                  + "matrix call; all-skip messages never reach a curator. no gate: every allowed "
                  + "workspace's curator sees the full batch and decides itself (best judgment, "
                  + "costs the most — for low-volume streams)."}
                disabled={busy !== null}
                onClick={() => {
                  const smart = a.routing === "smart" || (a.routing == null && a.triage);
                  void call("routing", `/api/streams/${a.id}/routing`, {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                      routing: smart ? "fanout" : "smart",
                      workspaces: a.workspaces ?? [],
                    }),
                  });
                }}>
                {(a.routing === "smart" || (a.routing == null && a.triage)) ? "smart gate" : "no gate"}
              </button>
              <span className="sy-stream-routes">
                {body.workspaces.map((w) => (
                  <label key={w.path} className="sy-stream-route"
                    title={`Allow this stream to be curated into ${w.name}`}>
                    <input
                      type="checkbox"
                      checked={(a.workspaces ?? []).includes(w.path)}
                      disabled={busy !== null}
                      onChange={(e) => {
                        const cur = new Set(a.workspaces ?? []);
                        if (e.target.checked) cur.add(w.path); else cur.delete(w.path);
                        void call("routing", `/api/streams/${a.id}/routing`, {
                          method: "POST",
                          headers: { "Content-Type": "application/json" },
                          body: JSON.stringify({
                            routing: (a.routing === "smart" || (a.routing == null && a.triage))
                              ? "smart" : "fanout",
                            workspaces: [...cur],
                          }),
                        });
                      }}
                    />
                    {w.name}
                  </label>
                ))}
              </span>
            </>
          )}
          {confirmRemove === a.id ? (
            <>
              <button type="button" className="sy-confirm-btn" disabled={busy !== null}
                onClick={() => void call("remove", `/api/streams/${a.id}/remove`, { method: "POST" })
                  .then(() => setConfirmRemove(null))}>
                Really remove
              </button>
              <button type="button" className="sy-confirm-btn"
                onClick={() => setConfirmRemove(null)}>Keep</button>
            </>
          ) : (
            <button type="button" className="sy-confirm-btn"
              onClick={() => setConfirmRemove(a.id)}>Remove</button>
          )}
        </div>
      ))}
      <div className="sy-settings-perm-row" style={{ flexWrap: "wrap", gap: 6, marginTop: 10 }}>
        <select className="sy-settings-input" value={prov}
          onChange={(e) => {
            // Reset per-provider credentials so stale fields from the
            // previous provider aren't submitted (they'd land on the
            // account as junk keys). Keep the generic label.
            setProv(e.target.value);
            setFieldVals({});
            setForm((f) => ({ ...f, client_id: "", client_secret: "", tenant: "" }));
            setStatus(null);
          }}>
          {Object.entries(body.providers).map(([k, v]) => (
            <option key={k} value={k}>{v.label}</option>
          ))}
        </select>
        <input className="sy-settings-input" placeholder="label (e.g. work mail)"
          value={form.label}
          onChange={(e) => setForm({ ...form, label: e.target.value })} />
        {pinfo?.auth === "password" ? (
          <>
            {pinfo.fields.map((f) => (
              <input
                key={f.key}
                className="sy-settings-input"
                type={f.secret ? "password" : "text"}
                placeholder={f.label}
                style={{ minWidth: 160 }}
                value={fieldVals[f.key] ?? ""}
                onChange={(e) => setFieldVals({ ...fieldVals, [f.key]: e.target.value })}
              />
            ))}
          </>
        ) : (
          <>
            <input className="sy-settings-input" placeholder="client ID" style={{ minWidth: 200 }}
              value={form.client_id}
              onChange={(e) => setForm({ ...form, client_id: e.target.value })} />
            {pinfo?.needs_secret && (
              <input className="sy-settings-input" type="password" placeholder="client secret"
                value={form.client_secret}
                onChange={(e) => setForm({ ...form, client_secret: e.target.value })} />
            )}
            {prov === "msgraph" && (
              <input className="sy-settings-input" placeholder="tenant (or 'common')"
                value={form.tenant}
                onChange={(e) => setForm({ ...form, tenant: e.target.value })} />
            )}
          </>
        )}
        <button type="button" className="sy-confirm-btn"
          disabled={busy !== null || (pinfo?.auth === "password"
            ? pinfo.fields.some((f) => f.required && !(fieldVals[f.key] ?? "").trim())
            : !form.client_id.trim())}
          onClick={() => void add()}>
          {busy === "add" ? "Verifying…" : "Add"}
        </button>
      </div>
      {pinfo && (
        <p className="sy-settings-blurb" style={{ marginTop: 6, fontSize: "0.85em" }}>
          {linkify(pinfo.setup_help)}
          {pinfo.auth === "oauth" && (
            <>
              {" "}Redirect URI for the app registration:{" "}
              <code>{body.redirect_uri}</code>
            </>
          )}
        </p>
      )}
      {status && (
        <p className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}>
          {status.msg}
        </p>
      )}
    </section>
  );
}

type PurgeRow = {
  thread_id: string;
  title: string | null;
  kind: string;
  updated_at: number;
  archived: boolean;
  event_count: number;
  selected?: boolean;
};

/** History purge panel. Deleting a thread from the switcher keeps its
 *  events (rail philosophy); THIS is the explicit, rare opt-out that
 *  hard-deletes. Flow: pick a date cutoff and/or a topic instruction →
 *  Preview (topic uses one un-logged LLM call) → checkbox list of
 *  candidates, pre-selected per the match → deselect / refine → Purge
 *  with a two-step confirm. */
function HistoryPanel({ open }: { open: boolean }) {
  const [before, setBefore] = useState("");        // yyyy-mm-dd
  const [topic, setTopic] = useState("");
  const [rows, setRows] = useState<PurgeRow[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [status, setStatus] = useState<{ ok: boolean; msg: string } | null>(null);

  useEffect(() => {
    if (!open) { setRows(null); setStatus(null); setConfirming(false); }
  }, [open]);

  const preview = async () => {
    setBusy(true);
    setStatus(null);
    setConfirming(false);
    try {
      const body: { before?: number; instructions?: string } = {};
      if (before) body.before = new Date(`${before}T23:59:59`).getTime() / 1000;
      if (topic.trim()) body.instructions = topic.trim();
      const r = await fetch("/api/history/purge-preview", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const b = await r.json() as { threads?: PurgeRow[]; error?: string };
      if (!r.ok) {
        setStatus({ ok: false, msg: b.error || `HTTP ${r.status}` });
        return;
      }
      setRows(b.threads ?? []);
      if (!topic.trim() && !before) {
        setStatus({
          ok: true,
          msg: "Showing all threads (none pre-selected). Tick the ones to purge, or narrow by date / topic first.",
        });
      }
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const purge = async () => {
    const ids = (rows ?? []).filter((r) => r.selected).map((r) => r.thread_id);
    if (ids.length === 0) return;
    setBusy(true);
    try {
      const r = await fetch("/api/history/purge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ thread_ids: ids }),
      });
      const b = await r.json() as { threads?: number; events?: number; error?: string };
      if (!r.ok) {
        setStatus({ ok: false, msg: b.error || `HTTP ${r.status}` });
        return;
      }
      setStatus({
        ok: true,
        msg: `Purged ${b.threads} thread${b.threads === 1 ? "" : "s"} (${b.events} events) permanently.`,
      });
      setRows(null);
      setConfirming(false);
    } catch (e) {
      setStatus({ ok: false, msg: (e as Error).message });
    } finally {
      setBusy(false);
    }
  };

  const selectedCount = (rows ?? []).filter((r) => r.selected).length;

  return (
    <section className="sy-settings-packs">
      <h3 className="sy-settings-h3">History · purge</h3>
      <p className="sy-settings-blurb">
        Removing a thread from the switcher (✕ in the thread picker)
        keeps its events in the rail log, still searchable by recall.
        Purging here deletes threads and their events{" "}
        <strong>permanently</strong> — rows, search index, embeddings.
        Preview first; nothing is deleted until you confirm.
      </p>
      <div className="sy-settings-perm-row" style={{ gap: 8, flexWrap: "wrap" }}>
        <label style={{ display: "flex", alignItems: "center", gap: 6 }}>
          last active before
          <input
            type="date"
            value={before}
            onChange={(e) => setBefore(e.target.value)}
            className="sy-settings-input"
          />
        </label>
        <input
          type="text"
          className="sy-settings-input"
          style={{ flex: 1, minWidth: 220 }}
          placeholder="…and/or a topic, e.g. “anything about the OAuth spike” (one LLM call, not recorded in the rail)"
          value={topic}
          onChange={(e) => setTopic(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") void preview(); }}
        />
        <button
          type="button"
          className="sy-confirm-btn"
          disabled={busy}
          onClick={() => void preview()}
        >
          {busy && rows === null ? "Previewing…" : rows ? "Refine preview" : "Preview"}
        </button>
      </div>
      {rows !== null && (
        <div className="sy-purge-list">
          {rows.length === 0 && (
            <p className="sy-settings-blurb">No matching threads.</p>
          )}
          {rows.map((r) => (
            <label key={r.thread_id} className="sy-purge-row">
              <input
                type="checkbox"
                checked={r.selected === true}
                onChange={(e) => setRows((cur) => (cur ?? []).map(
                  (x) => x.thread_id === r.thread_id
                    ? { ...x, selected: e.target.checked }
                    : x,
                ))}
              />
              <span className="sy-purge-title">
                {r.kind === "interactive-pty" ? ">_ " : ""}
                {r.title || "(untitled)"}
              </span>
              {r.archived && <span className="sy-purge-chip">archived</span>}
              <span className="sy-purge-meta">
                {r.event_count} events · {new Date(r.updated_at * 1000).toLocaleDateString()}
              </span>
            </label>
          ))}
          {rows.length > 0 && (
            <div className="sy-settings-perm-row" style={{ marginTop: 8 }}>
              <span className="sy-spacer" />
              {!confirming ? (
                <button
                  type="button"
                  className="sy-confirm-btn"
                  disabled={busy || selectedCount === 0}
                  onClick={() => setConfirming(true)}
                >
                  Purge {selectedCount} selected…
                </button>
              ) : (
                <>
                  <span style={{ color: "var(--err, #f38ba8)" }}>
                    Permanently delete {selectedCount} thread{selectedCount === 1 ? "" : "s"}? This cannot be undone.
                  </span>
                  <button
                    type="button"
                    className="sy-confirm-btn"
                    disabled={busy}
                    onClick={() => void purge()}
                  >
                    {busy ? "Purging…" : "Yes, purge"}
                  </button>
                  <button
                    type="button"
                    className="sy-confirm-btn"
                    onClick={() => setConfirming(false)}
                  >
                    Cancel
                  </button>
                </>
              )}
            </div>
          )}
        </div>
      )}
      {status && (
        <p className={"sy-settings-status" + (status.ok ? "" : " sy-settings-status--err")}>
          {status.msg}
        </p>
      )}
    </section>
  );
}


// ── Easter egg: "fire thrusters?" ─────────────────────────────────
// Cryptic toggle at the very bottom of Settings. Arms a temporary
// Hopper tab hosting the vendored Mars Hopper game. No blurb, no
// section heading — just a quiet switch for those who notice.

function ThrustersEgg({ open, onClose }: { open: boolean; onClose: () => void }) {
  const [armed, setArmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [known, setKnown] = useState(false);

  useEffect(() => {
    if (!open) return;
    let live = true;
    fetch("/api/easter/thrusters")
      .then((r) => (r.ok ? r.json() : null))
      .then((b: { armed?: boolean } | null) => {
        if (!live || !b) return;
        setArmed(!!b.armed);
        setKnown(true);
      })
      .catch(() => { /* older daemon — hide egg */ });
    return () => { live = false; };
  }, [open]);

  const toggle = async () => {
    if (busy) return;
    const next = !armed;
    setBusy(true);
    try {
      const r = await fetch("/api/easter/thrusters", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ armed: next }),
      });
      if (!r.ok) return;
      setArmed(next);
      // If arming, close Settings so the Hopper tab is front and center.
      if (next) onClose();
    } finally {
      setBusy(false);
    }
  };

  // Hide entirely if the daemon has no easter endpoint (old builds).
  if (!known) return null;

  return (
    <div className="sy-settings-egg" title="…">
      <label className="sy-settings-egg-label">
        <span className="sy-settings-egg-q">fire thrusters?</span>
        <button
          type="button"
          role="switch"
          aria-checked={armed}
          aria-label="fire thrusters?"
          className={
            "sy-settings-egg-switch"
            + (armed ? " sy-settings-egg-switch--on" : "")
          }
          disabled={busy}
          onClick={() => void toggle()}
        >
          <span className="sy-settings-egg-knob" />
        </button>
      </label>
    </div>
  );
}


/** Render a string with bare http(s) URLs turned into <a> tags so the
 *  user can click install / docs links from auth_help text. Splits on
 *  the URL regex and interleaves the parts. */
const _URL_RE = /(https?:\/\/[^\s)]+[^\s).,;:'"!?])/g;
function linkify(text: string): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let last = 0;
  for (const m of text.matchAll(_URL_RE)) {
    const idx = m.index ?? 0;
    if (idx > last) parts.push(text.slice(last, idx));
    parts.push(
      <a key={`u-${idx}`} href={m[0]} target="_blank" rel="noreferrer">
        {m[0]}
      </a>,
    );
    last = idx + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return parts;
}
