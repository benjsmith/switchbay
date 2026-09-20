import { useCallback, useEffect, useRef, useState } from "react";
import { sameWorkspace, workspaceKey } from "../../lib/webPolicy";

type CommsItem = {
  key: string;
  provider?: string;
  account_id?: string;
  stable_id?: string;
  kind?: string;
  status?: string;
  block_reason?: string;
  block_detail?: string;
  subject?: string;
  sender?: string;
  deep_link?: string;
  labels?: string[];
  approved_workspaces?: string[];
  suggested_workspaces?: string[];
  suggested_relevance?: Record<string, number>;
  content_capability?: string;
  content_capability_reason?: string;
  ingest_state?: string;
  ingest_error?: string;
};

type QueueBody = {
  items?: CommsItem[];
  workspace?: string;
  workspaces?: { path: string; name: string }[];
};

function readFocusedWorkspace(): string {
  try {
    const raw = window.localStorage.getItem("sy.workspaces.snapshot");
    if (!raw) return "";
    const parsed = JSON.parse(raw) as { workspace?: string };
    return typeof parsed.workspace === "string" ? parsed.workspace : "";
  } catch {
    return "";
  }
}

/**
 * Comms review — email threads and Teams/Slack channels.
 * Patterned after Reviews: backlog, not a rail card. No body previews.
 * Bound to the focused workspace (stale GET/POST ignored).
 */
export default function CommsTab() {
  const [items, setItems] = useState<CommsItem[]>([]);
  const [idx, setIdx] = useState(0);
  const [workspaces, setWorkspaces] = useState<{ path: string; name: string }[]>([]);
  const [boundWs, setBoundWs] = useState(readFocusedWorkspace);
  const [approveWs, setApproveWs] = useState(readFocusedWorkspace);
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const epochRef = useRef(0);

  const loadQueue = useCallback(async (explicitWs?: string) => {
    const ws = workspaceKey(explicitWs || readFocusedWorkspace());
    const epoch = ++epochRef.current;
    try {
      const q = ws ? `?workspace=${encodeURIComponent(ws)}` : "";
      const r = await fetch(`/api/comms/review${q}`);
      if (epoch !== epochRef.current) return;
      if (!r.ok) return;
      const body = (await r.json()) as QueueBody;
      if (epoch !== epochRef.current) return;
      const bodyWs = workspaceKey(body.workspace);
      if (bodyWs && ws && !sameWorkspace(bodyWs, ws)) return;
      const next = body.items ?? [];
      setItems(next);
      setWorkspaces(body.workspaces ?? []);
      if (ws) {
        setBoundWs(ws);
        setApproveWs((cur) => (workspaceKey(cur) ? cur : ws));
      }
      setIdx((i) => Math.min(i, Math.max(0, next.length - 1)));
    } catch { /* best-effort */ }
  }, []);

  useEffect(() => {
    if (boundWs) setApproveWs(boundWs);
  }, [boundWs]);

  useEffect(() => {
    const syncBound = () => {
      const next = readFocusedWorkspace();
      setBoundWs((prev) => (sameWorkspace(prev, next) || (!prev && !next) ? prev : next));
    };
    void loadQueue(boundWs);
    const onCh = () => { void loadQueue(readFocusedWorkspace()); };
    window.addEventListener("sy:comms-review", onCh);
    window.addEventListener("storage", syncBound);
    const iv = window.setInterval(syncBound, 1000);
    return () => {
      window.removeEventListener("sy:comms-review", onCh);
      window.removeEventListener("storage", syncBound);
      window.clearInterval(iv);
    };
  }, [loadQueue, boundWs]);

  const current = items[idx] ?? null;

  const act = async (action: "approve" | "reject" | "revoke") => {
    if (!current) return;
    const epoch = ++epochRef.current;
    const ws = workspaceKey(boundWs || readFocusedWorkspace());
    setBusy(true);
    setErr(null);
    try {
      const payload: Record<string, string> = { key: current.key, action };
      if (ws) payload.workspace = action === "approve" ? (approveWs || ws) : ws;
      if (action === "approve") {
        if (!payload.workspace) {
          setErr("workspace is required");
          return;
        }
      }
      const r = await fetch("/api/comms/review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (epoch !== epochRef.current) return;
      const b = await r.json().catch(() => ({} as {
        error?: string; workspace?: string; ingest_error?: string; ingest_state?: string;
      }));
      if (epoch !== epochRef.current) return;
      const bodyWs = workspaceKey((b as { workspace?: string }).workspace);
      if (bodyWs && ws && !sameWorkspace(bodyWs, ws) && action !== "approve") return;
      if (!r.ok) { setErr(b.error || `HTTP ${r.status}`); return; }
      if (action === "approve" && b.ingest_error) setErr(b.ingest_error);
      window.dispatchEvent(new CustomEvent("sy:comms-review"));
      await loadQueue(ws);
    } catch (e) {
      setErr((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const closeTab = async () => {
    try {
      const ws = workspaceKey(boundWs || readFocusedWorkspace());
      const q = ws ? `?workspace=${encodeURIComponent(ws)}` : "";
      await fetch(`/api/comms/review/close${q}`, { method: "POST" });
    } catch { /* hello drops the tab */ }
  };

  if (!current) {
    return (
      <div className="sy-report-empty">
        <div className="sy-report-empty-inner">
          <div className="sy-report-glyph">✉</div>
          <p>
            Comms review — email threads and Teams/Slack channels.
            Discovery is metadata only. Nothing is added to the wiki
            until you approve a source for a workspace. Teams and Slack
            can be listed here; their message bodies cannot be retrieved.
          </p>
          <div style={{ display: "flex", gap: 8, justifyContent: "center", marginTop: 12 }}>
            <button type="button" className="sy-confirm-btn" onClick={() => void closeTab()}>
              ✕ close
            </button>
          </div>
        </div>
      </div>
    );
  }

  const suggested = current.suggested_workspaces ?? [];
  const blocked = current.status === "blocked" || current.status === "revoked";
  const secret = current.block_reason === "secret" || current.block_reason === "secret_mark"
    || current.block_reason === "tenant_secret_label";
  const failClosed = current.content_capability === "fail_closed";
  const canApprove = !busy && !blocked && !secret && current.status !== "revoked" && !failClosed;

  return (
    <div className="sy-report-host">
      <div className="sy-report-bar">
        <span className="sy-report-title">
          {current.subject || current.stable_id || "Comms"}
        </span>
        {items.length > 0 && (
          <span className="sy-report-count">{idx + 1} / {items.length}</span>
        )}
        <div className="sy-report-bar-actions">
          {items.length > 1 && (
            <>
              <button type="button" className="sy-report-pop" disabled={idx <= 0}
                onClick={() => setIdx((i) => Math.max(0, i - 1))}>← prev</button>
              <button type="button" className="sy-report-pop" disabled={idx >= items.length - 1}
                onClick={() => setIdx((i) => Math.min(items.length - 1, i + 1))}>next →</button>
            </>
          )}
          <button type="button" className="sy-report-pop" onClick={() => void closeTab()}>
            ✕ close
          </button>
        </div>
      </div>
      {err && <div className="sy-report-error">{err}</div>}
      <div className="sy-review-body">
        <div className="sy-review-meta">
          <code>{current.provider} · {current.kind} · {current.status}</code>
          {current.sender && <span>{current.sender}</span>}
          {current.deep_link && (
            <a href={current.deep_link} target="_blank" rel="noreferrer">open source</a>
          )}
          {current.approved_workspaces && current.approved_workspaces.length > 0 && (
            <span>approved for {current.approved_workspaces.map((p) => p.split("/").pop()).join(", ")}</span>
          )}
          {suggested.length > 0 && (
            <p className="sy-review-oneline">
              Suggested relevance: {suggested.map((p) => p.split("/").pop()).join(", ")}
              {" "}(not approved)
            </p>
          )}
          {failClosed && (
            <p className="sy-review-oneline">
              {current.content_capability_reason
                || "Content fetch is not available for this adapter. Approval does not retrieve message bodies."}
            </p>
          )}
          {current.block_detail && (
            <p className="sy-review-oneline">{current.block_detail}</p>
          )}
          {current.status === "approved" && current.ingest_error && (
            <p className="sy-review-oneline">{current.ingest_error}</p>
          )}
          {current.status === "approved" && !current.ingest_error
            && current.ingest_state === "pending" && (
            <p className="sy-review-oneline">Approved — not in the wiki yet.</p>
          )}
        </div>
        <p className="sy-review-oneline" style={{ opacity: 0.8 }}>
          No body preview. Unapproved sources contribute metadata only.
        </p>
        <div className="sy-review-actions">
          <label className="sy-review-oneline">
            Workspace{" "}
            <select
              value={approveWs}
              onChange={(e) => setApproveWs(e.target.value)}
              disabled={busy}
            >
              {workspaces.map((w) => (
                <option key={w.path} value={w.path}>{w.name}</option>
              ))}
              {approveWs && !workspaces.some((w) => w.path === approveWs) && (
                <option value={approveWs}>{approveWs.split("/").pop()}</option>
              )}
            </select>
          </label>
          <div className="sy-review-btns">
            <button type="button" className="sy-confirm-btn sy-confirm-btn--primary"
              disabled={!canApprove}
              title={failClosed
                ? "This adapter cannot retrieve message content; listing only."
                : "Approve this source for the selected workspace and pull currently clear mail."}
              onClick={() => void act("approve")}>
              {failClosed ? "Content cannot be retrieved" : "Approve for workspace"}
            </button>
            <button type="button" className="sy-confirm-btn" disabled={busy}
              onClick={() => void act("reject")}>
              Reject
            </button>
            <button type="button" className="sy-confirm-btn" disabled={busy}
              onClick={() => void act("revoke")}>
              Revoke
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
