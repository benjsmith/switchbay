import { useCallback, useEffect, useState } from "react";

export type Schedule = {
  id: string;
  title: string;
  prompt: string;
  frequency: string;
  every_hours?: number;
  enabled?: boolean;
  preference?: number | null;
  created_at?: number;
  created_day?: string;
  edited_at?: number;
  last_run_at?: number | null;
  run_count?: number;
  running_run_id?: string | null;
  scope?: "global" | "workspace";
  workspace?: string | null;
  workspace_name?: string;
};

type WsRow = { path: string; name: string };

const FREQS = [
  { id: "hourly", label: "Hourly" },
  { id: "daily", label: "Daily" },
  { id: "weekly", label: "Weekly" },
  { id: "every_n_hours", label: "Every N hours" },
];

function fmt(ts?: number | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return "—";
  }
}

export default function SchedulesPanel({ compact }: { compact?: boolean }) {
  const [items, setItems] = useState<Schedule[]>([]);
  const [workspaces, setWorkspaces] = useState<WsRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [draft, setDraft] = useState<Partial<Schedule>>({});

  const reload = useCallback(async () => {
    try {
      const r = await fetch("/api/schedules");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = (await r.json()) as { schedules?: Schedule[]; workspaces?: WsRow[] };
      setItems(body.schedules ?? []);
      setWorkspaces(body.workspaces ?? []);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    const id = window.setInterval(() => { void reload(); }, 8000);
    return () => window.clearInterval(id);
  }, [reload]);

  const startNew = (seed?: Partial<Schedule>) => {
    setEditing("new");
    setDraft({
      title: seed?.title || "Desk",
      prompt: seed?.prompt || "/curate",
      frequency: seed?.frequency || "daily",
      every_hours: seed?.every_hours ?? 24,
      enabled: seed?.enabled ?? true,
      preference: seed?.preference ?? 1,
      scope: seed?.scope || "workspace",
      workspace: seed?.workspace ?? workspaces[0]?.path ?? null,
    });
  };

  useEffect(() => {
    const onSeed = (ev: Event) => {
      const detail = (ev as CustomEvent<Partial<Schedule>>).detail;
      if (!detail) return;
      startNew(detail);
    };
    window.addEventListener("sy:schedule-new", onSeed);
    return () => window.removeEventListener("sy:schedule-new", onSeed);
  }, [workspaces]);

  const startEdit = (s: Schedule) => {
    setEditing(s.id);
    setDraft({ ...s });
  };

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      const payload = {
        title: draft.title,
        prompt: draft.prompt,
        frequency: draft.frequency,
        every_hours: draft.every_hours,
        enabled: draft.enabled,
        preference: draft.preference,
        scope: draft.scope || "workspace",
        workspace: draft.scope === "global" ? null : (draft.workspace || null),
        run_now: false,
      };
      if (editing === "new") {
        const r = await fetch("/api/schedules", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      } else if (editing) {
        const r = await fetch(`/api/schedules/${encodeURIComponent(editing)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      }
      setEditing(null);
      await reload();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const patchEnabled = async (s: Schedule, enabled: boolean) => {
    const r = await fetch(`/api/schedules/${encodeURIComponent(s.id)}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enabled }),
    });
    if (!r.ok) setError(`HTTP ${r.status}`);
    await reload();
  };

  const remove = async (id: string) => {
    if (!window.confirm("Dismiss this schedule?")) return;
    const r = await fetch(`/api/schedules/${encodeURIComponent(id)}`, { method: "DELETE" });
    if (!r.ok) {
      setError(`HTTP ${r.status}`);
      return;
    }
    if (editing === id) setEditing(null);
    await reload();
  };

  const runNow = async (id: string) => {
    const r = await fetch(`/api/schedules/${encodeURIComponent(id)}/run`, { method: "POST" });
    if (!r.ok) {
      setError(`HTTP ${r.status}`);
      return;
    }
    await reload();
  };

  const stop = async (s: Schedule) => {
    const r = await fetch(`/api/schedules/${encodeURIComponent(s.id)}/stop`, { method: "POST" });
    if (!r.ok) {
      setError(`HTTP ${r.status}`);
      return;
    }
    await reload();
  };

  return (
    <div className={compact ? "sy-schedules-panel" : "sy-schedules-tab"}>
      {!compact && (
        <div className="sy-schedules-header">
          <h2>Schedules</h2>
          <span className="sy-spacer" />
          <button type="button" className="sy-schedules-add" onClick={() => startNew()} title="Add schedule">+</button>
        </div>
      )}
      <p className="sy-schedules-blurb">
        Recurring Auto prompts. <strong>Start</strong> runs now (and turns
        the schedule on). <strong>On/Off</strong> is only whether future
        ticks fire. <strong>Stop</strong> cancels a live run.
        This workspace vs all wikis is the scope of each row.
      </p>
      {compact && (
        <div className="sy-schedules-toolbar">
          <button type="button" className="sy-agents-row-btn" onClick={() => startNew()}>+ schedule</button>
        </div>
      )}
      {error && <p className="sy-schedules-error">{error}</p>}
      {items.length === 0 && editing !== "new" && (
        <p className="sy-schedules-empty">No recurring desks yet.</p>
      )}
      <ul className="sy-schedules-list">
        {editing === "new" && (
          <li className="sy-schedules-row sy-schedules-row--edit">
            <Editor
              draft={draft}
              setDraft={setDraft}
              workspaces={workspaces}
              busy={busy}
              onSave={() => void save()}
              onCancel={() => setEditing(null)}
            />
          </li>
        )}
        {items.map((s) => (
          <li key={s.id} className="sy-schedules-row">
            {editing === s.id ? (
              <Editor
                draft={draft}
                setDraft={setDraft}
                workspaces={workspaces}
                busy={busy}
                onSave={() => void save()}
                onCancel={() => setEditing(null)}
              />
            ) : (
              <>
                <div className="sy-schedules-row-head">
                  <strong>{s.title || "Untitled"}</strong>
                  <span className="sy-schedules-freq">
                    {s.frequency === "every_n_hours" ? `every ${s.every_hours}h` : s.frequency}
                  </span>
                  <span className={"sy-schedules-chip" + (s.scope === "global" ? " sy-schedules-chip--global" : "")}>
                    {s.scope === "global" ? "all workspaces" : (s.workspace_name || "workspace")}
                  </span>
                  {s.running_run_id ? <span className="sy-schedules-chip sy-schedules-chip--live">running</span> : null}
                  {s.enabled === false ? <span className="sy-schedules-chip">off</span> : null}
                  <span className="sy-spacer" />
                  <button
                    type="button"
                    className="sy-schedules-btn"
                    onClick={() => {
                      void (async () => {
                        if (s.enabled === false) await patchEnabled(s, true);
                        await runNow(s.id);
                      })();
                    }}
                    title="Run this desk now (also turns the schedule on)"
                  >
                    Start
                  </button>
                  <button
                    type="button"
                    className="sy-schedules-btn"
                    onClick={() => void patchEnabled(s, s.enabled === false)}
                    title={s.enabled === false ? "Fire on the next tick" : "Skip future ticks until you turn it on"}
                  >
                    {s.enabled === false ? "Off" : "On"}
                  </button>
                  {s.running_run_id ? (
                    <button
                      type="button"
                      className="sy-schedules-btn"
                      onClick={() => void stop(s)}
                      title="Cancel the live run from this schedule"
                    >
                      Stop
                    </button>
                  ) : null}
                  <button type="button" className="sy-schedules-btn" onClick={() => startEdit(s)}>Edit</button>
                  <button type="button" className="sy-schedules-btn" onClick={() => void remove(s.id)}>Dismiss</button>
                </div>
                <pre className="sy-schedules-prompt">{(s.prompt || "").slice(0, 280) || "(empty prompt)"}</pre>
                <div className="sy-schedules-meta">
                  last run {fmt(s.last_run_at)}
                  {" · "}{s.run_count ?? 0} run{(s.run_count ?? 0) === 1 ? "" : "s"}
                </div>
              </>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function Editor({
  draft, setDraft, workspaces, busy, onSave, onCancel,
}: {
  draft: Partial<Schedule>;
  setDraft: (d: Partial<Schedule>) => void;
  workspaces: WsRow[];
  busy: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
  const scope = draft.scope === "global" ? "global" : "workspace";
  return (
    <div className="sy-schedules-editor">
      <input
        className="sy-schedules-input"
        value={draft.title ?? ""}
        onChange={(e) => setDraft({ ...draft, title: e.target.value })}
        placeholder="Title"
      />
      <div className="sy-schedules-freq-row">
        <select
          className="sy-schedules-input"
          value={scope}
          onChange={(e) => {
            const next = e.target.value === "global" ? "global" : "workspace";
            setDraft({
              ...draft,
              scope: next,
              workspace: next === "global" ? null : (draft.workspace || workspaces[0]?.path || null),
            });
          }}
          aria-label="Schedule scope"
        >
          <option value="workspace">This / a workspace</option>
          <option value="global">All workspaces</option>
        </select>
        {scope === "workspace" && (
          <select
            className="sy-schedules-input"
            value={draft.workspace || workspaces[0]?.path || ""}
            onChange={(e) => setDraft({ ...draft, workspace: e.target.value })}
            aria-label="Target workspace"
          >
            {workspaces.map((w) => (
              <option key={w.path} value={w.path}>{w.name}</option>
            ))}
          </select>
        )}
        <select
          className="sy-schedules-input"
          value={draft.frequency ?? "daily"}
          onChange={(e) => setDraft({ ...draft, frequency: e.target.value })}
        >
          {FREQS.map((f) => (
            <option key={f.id} value={f.id}>{f.label}</option>
          ))}
        </select>
        {draft.frequency === "every_n_hours" && (
          <input
            className="sy-schedules-input sy-schedules-input--n"
            type="number"
            min={1}
            value={draft.every_hours ?? 24}
            onChange={(e) => setDraft({ ...draft, every_hours: Number(e.target.value) })}
          />
        )}
        <label className="sy-schedules-check">
          <input
            type="checkbox"
            checked={draft.enabled !== false}
            onChange={(e) => setDraft({ ...draft, enabled: e.target.checked })}
          />
          enabled
        </label>
      </div>
      <textarea
        className="sy-schedules-textarea"
        rows={6}
        value={draft.prompt ?? ""}
        onChange={(e) => setDraft({ ...draft, prompt: e.target.value })}
        placeholder="Prompt Auto will run — e.g. /curate"
      />
      <div className="sy-schedules-editor-actions">
        <button type="button" className="sy-schedules-btn" disabled={busy} onClick={onSave}>Save</button>
        <button type="button" className="sy-schedules-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
