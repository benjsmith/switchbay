import { useCallback, useEffect, useState } from "react";

type Schedule = {
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
};

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

export default function SchedulesTab() {
  const [items, setItems] = useState<Schedule[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [editing, setEditing] = useState<string | "new" | null>(null);
  const [draft, setDraft] = useState<Partial<Schedule>>({});

  const reload = useCallback(async () => {
    try {
      const r = await fetch("/api/schedules");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const body = (await r.json()) as { schedules?: Schedule[] };
      setItems(body.schedules ?? []);
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => { void reload(); }, [reload]);

  const startNew = () => {
    setEditing("new");
    setDraft({
      title: "Overnight desk",
      prompt: "",
      frequency: "daily",
      every_hours: 24,
      enabled: true,
      preference: 1,
    });
  };

  const startEdit = (s: Schedule) => {
    setEditing(s.id);
    setDraft({ ...s });
  };

  const save = async () => {
    if (busy) return;
    setBusy(true);
    try {
      if (editing === "new") {
        const r = await fetch("/api/schedules", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: draft.title,
            prompt: draft.prompt,
            frequency: draft.frequency,
            every_hours: draft.every_hours,
            enabled: draft.enabled,
            preference: draft.preference,
            run_now: false,
          }),
        });
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
      } else if (editing) {
        const r = await fetch(`/api/schedules/${encodeURIComponent(editing)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            title: draft.title,
            prompt: draft.prompt,
            frequency: draft.frequency,
            every_hours: draft.every_hours,
            enabled: draft.enabled,
            preference: draft.preference,
          }),
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

  const remove = async (id: string) => {
    if (!window.confirm("Delete this schedule?")) return;
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

  return (
    <div className="sy-schedules-tab">
      <div className="sy-schedules-header">
        <h2>Schedules</h2>
        <span className="sy-spacer" />
        <button type="button" className="sy-schedules-add" onClick={startNew} title="Add schedule">
          +
        </button>
      </div>
      <p className="sy-schedules-blurb">
        Recurring Auto prompts for this workspace. Daily overnight desks
        belong here. Frequency is wall-clock since last run; a new
        schedule is due immediately unless you turn it off.
      </p>
      {error && <p className="sy-schedules-error">{error}</p>}
      {items.length === 0 && editing !== "new" && (
        <p className="sy-schedules-empty">No schedules yet. Use + to add one.</p>
      )}
      <ul className="sy-schedules-list">
        {editing === "new" && (
          <li className="sy-schedules-row sy-schedules-row--edit">
            <Editor draft={draft} setDraft={setDraft} busy={busy} onSave={() => void save()} onCancel={() => setEditing(null)} />
          </li>
        )}
        {items.map((s) => (
          <li key={s.id} className="sy-schedules-row">
            {editing === s.id ? (
              <Editor draft={draft} setDraft={setDraft} busy={busy} onSave={() => void save()} onCancel={() => setEditing(null)} />
            ) : (
              <>
                <div className="sy-schedules-row-head">
                  <strong>{s.title || "Untitled"}</strong>
                  <span className="sy-schedules-freq">{s.frequency}{s.frequency === "every_n_hours" ? ` · ${s.every_hours}h` : ""}</span>
                  {s.running_run_id ? <span className="sy-schedules-chip">running</span> : null}
                  {s.enabled === false ? <span className="sy-schedules-chip">off</span> : null}
                  <span className="sy-spacer" />
                  <button type="button" className="sy-schedules-btn" onClick={() => void runNow(s.id)}>Run</button>
                  <button type="button" className="sy-schedules-btn" onClick={() => startEdit(s)}>Edit</button>
                  <button type="button" className="sy-schedules-btn" onClick={() => void remove(s.id)}>Delete</button>
                </div>
                <pre className="sy-schedules-prompt">{(s.prompt || "").slice(0, 400) || "(empty prompt)"}</pre>
                <div className="sy-schedules-meta">
                  Started {s.created_day || fmt(s.created_at)}
                  {" · "}edited {fmt(s.edited_at)}
                  {" · "}last run {fmt(s.last_run_at)}
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
  draft, setDraft, busy, onSave, onCancel,
}: {
  draft: Partial<Schedule>;
  setDraft: (d: Partial<Schedule>) => void;
  busy: boolean;
  onSave: () => void;
  onCancel: () => void;
}) {
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
        rows={10}
        value={draft.prompt ?? ""}
        onChange={(e) => setDraft({ ...draft, prompt: e.target.value })}
        placeholder="Prompt Auto will run"
      />
      <div className="sy-schedules-editor-actions">
        <button type="button" className="sy-schedules-btn" disabled={busy} onClick={onSave}>Save</button>
        <button type="button" className="sy-schedules-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
