import { useCallback, useEffect, useState } from "react";
import SchedulesPanel from "../schedules/SchedulesPanel";

type StandingDesk = {
  desk_id: string;
  label?: string;
  slash?: string | null;
  state: string;
  chief_provider?: string | null;
  chief_model?: string | null;
  run_id?: string | null;
  objective?: string | null;
  updated_at?: number;
};

type InterruptedRow = {
  orchestration_id: string;
  objective?: string;
  elapsed_s?: number;
  completed?: string[];
  phase?: string;
  resume_at?: number | null;
  stop_reason?: string;
};

function fmt(ts?: number | null): string {
  if (!ts) return "—";
  try {
    return new Date(ts * 1000).toLocaleString();
  } catch {
    return "—";
  }
}

export default function DesksPanel({ focusedWs }: { focusedWs?: string }) {
  const [desks, setDesks] = useState<StandingDesk[]>([]);
  const [interrupted, setInterrupted] = useState<InterruptedRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    const q = focusedWs ? `?workspace=${encodeURIComponent(focusedWs)}` : "";
    try {
      const [d, i] = await Promise.all([
        fetch(`/api/desks${q}`),
        fetch("/api/orchestration/interrupted"),
      ]);
      if (d.ok) {
        const body = (await d.json()) as { desks?: StandingDesk[] };
        setDesks(body.desks ?? []);
      }
      if (i.ok) {
        const body = (await i.json()) as { runs?: InterruptedRow[] };
        setInterrupted(body.runs ?? []);
      }
      setError(null);
    } catch (e) {
      setError((e as Error).message);
    }
  }, [focusedWs]);

  useEffect(() => { void reload(); }, [reload]);
  useEffect(() => {
    const id = window.setInterval(() => { void reload(); }, 8000);
    return () => window.clearInterval(id);
  }, [reload]);

  const start = async (desk: StandingDesk) => {
    const q = focusedWs ? `?workspace=${encodeURIComponent(focusedWs)}` : "";
    const r = await fetch(
      `/api/desks/${encodeURIComponent(desk.desk_id)}/start${q}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(
          desk.state === "quiet" && desk.run_id
            ? {}
            : { prompt: desk.objective || "" },
        ),
      },
    );
    if (!r.ok) setError(`HTTP ${r.status}`);
    await reload();
  };

  const dismiss = async (desk: StandingDesk) => {
    const q = focusedWs ? `?workspace=${encodeURIComponent(focusedWs)}` : "";
    const r = await fetch(
      `/api/desks/${encodeURIComponent(desk.desk_id)}/dismiss${q}`,
      { method: "POST" },
    );
    if (!r.ok) setError(`HTTP ${r.status}`);
    await reload();
  };

  const edit = (desk: StandingDesk) => {
    const brief = (desk.objective || "").trim();
    const text = desk.slash
      ? (brief ? `/${desk.slash} ${brief}` : `/${desk.slash} `)
      : brief;
    window.dispatchEvent(new CustomEvent("sy:rail-set-input", {
      detail: { text, focus: true },
    }));
  };

  const schedule = (desk: StandingDesk) => {
    window.dispatchEvent(new CustomEvent("sy:schedule-new", {
      detail: {
        title: `${desk.label || desk.desk_id} desk`,
        prompt: desk.slash
          ? (desk.objective ? `/${desk.slash} ${desk.objective}` : `/${desk.slash}`)
          : (desk.objective || ""),
      },
    }));
  };

  const resume = async (row: InterruptedRow) => {
    await fetch(
      `/api/orchestration/${encodeURIComponent(row.orchestration_id)}/resume`,
      { method: "POST" },
    );
    await reload();
  };

  const dismissInterrupted = async (row: InterruptedRow) => {
    await fetch(
      `/api/orchestration/${encodeURIComponent(row.orchestration_id)}/dismiss`,
      { method: "POST" },
    );
    await reload();
  };

  return (
    <div className="sy-schedules-panel">
      {error && <p className="sy-schedules-error">{error}</p>}
      <p className="sy-schedules-blurb">
        Standing desks stay until you dismiss them. A second slideshow
        or <code>/curate</code> reuses the same desk — it is not a new
        row per ask. Any <code>/… stop</code> quiets the DAG (Start
        resumes it). <strong>Dismiss</strong> (or{" "}
        <code>/work dismiss</code>) tears the desk down.{" "}
        <strong>Start</strong> runs now; <strong>Schedule</strong> adds a
        recurring tick. Wiki lookups do not seat a desk.
      </p>
      {desks.length === 0 && interrupted.length === 0 && (
        <p className="sy-schedules-empty">
          No standing desks. <code>/curate</code>, <code>/work</code>, or{" "}
          <code>/code</code> seats one. Asking for a slideshow reuses Deck.
          Wiki lookups stay a one-shot.
        </p>
      )}
      <ul className="sy-schedules-list">
        {desks.map((desk) => (
          <li key={desk.desk_id} className="sy-schedules-row">
            <div className="sy-schedules-row-head">
              <strong>{desk.label || desk.desk_id}</strong>
              {desk.slash ? (
                <span className="sy-schedules-freq">/{desk.slash}</span>
              ) : null}
              <span
                className={
                  "sy-schedules-chip"
                  + (desk.state === "working" ? " sy-schedules-chip--live" : "")
                }
              >
                {desk.state}
              </span>
              {desk.chief_model ? (
                <span className="sy-schedules-freq">{desk.chief_model}</span>
              ) : null}
              <span className="sy-spacer" />
              {desk.state !== "working" && (
                <button
                  type="button"
                  className="sy-schedules-btn"
                  onClick={() => void start(desk)}
                  title="Run this desk now"
                >
                  Start
                </button>
              )}
              <button
                type="button"
                className="sy-schedules-btn"
                onClick={() => edit(desk)}
                title="Edit the brief in the rail"
              >
                Edit
              </button>
              <button
                type="button"
                className="sy-schedules-btn"
                onClick={() => schedule(desk)}
                title="Add a recurring schedule for this desk"
              >
                Schedule
              </button>
              <button
                type="button"
                className="sy-schedules-btn"
                onClick={() => void dismiss(desk)}
                title="Tear this desk down"
              >
                Dismiss
              </button>
            </div>
            <pre className="sy-schedules-prompt">
              {desk.objective || "(no brief yet)"}
            </pre>
            <div className="sy-schedules-meta">updated {fmt(desk.updated_at)}</div>
          </li>
        ))}
        {interrupted.map((row) => (
          <li key={row.orchestration_id} className="sy-schedules-row">
            <div className="sy-schedules-row-head">
              <strong>Interrupted</strong>
              <span className="sy-schedules-chip">{row.phase || "paused"}</span>
              <span className="sy-schedules-freq">{row.orchestration_id}</span>
              <span className="sy-spacer" />
              <button
                type="button"
                className="sy-schedules-btn"
                onClick={() => void resume(row)}
                title="Resume without re-running finished nodes"
              >
                Start
              </button>
              <button
                type="button"
                className="sy-schedules-btn"
                onClick={() => void dismissInterrupted(row)}
                title="Drop this checkpoint"
              >
                Dismiss
              </button>
            </div>
            <pre className="sy-schedules-prompt">
              {row.objective || "orchestration"}
            </pre>
            <div className="sy-schedules-meta">
              {(row.completed ?? []).length} node
              {(row.completed ?? []).length === 1 ? "" : "s"} done
              {row.stop_reason ? ` · ${row.stop_reason}` : ""}
            </div>
          </li>
        ))}
      </ul>
      <h3 className="sy-desks-subh">Recurring</h3>
      <SchedulesPanel compact />
    </div>
  );
}
