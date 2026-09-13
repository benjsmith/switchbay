import { useEffect, useState } from "react";

export type WebPolicy = {
  enabled: boolean;
  admin_allows: boolean;
  requested?: boolean;
  workspace?: string;
};

let state: WebPolicy = { enabled: false, admin_allows: true };
let epoch = 0;
const listeners = new Set<() => void>();

export function workspaceKey(p?: string | null): string {
  return (p || "").replace(/\/+$/, "");
}

export function sameWorkspace(a?: string | null, b?: string | null): boolean {
  const ka = workspaceKey(a);
  const kb = workspaceKey(b);
  return ka.length > 0 && ka === kb;
}

function notify(): void {
  listeners.forEach((fn) => fn());
}

function bump(): void {
  epoch += 1;
}

function policyFrom(next: Partial<WebPolicy>, fallbackWs?: string): WebPolicy {
  const ws = workspaceKey(next.workspace) || workspaceKey(fallbackWs) || state.workspace;
  return {
    enabled: Boolean(next.enabled),
    admin_allows: next.admin_allows !== undefined ? Boolean(next.admin_allows) : state.admin_allows,
    requested: next.requested !== undefined ? Boolean(next.requested) : next.requested,
    workspace: ws,
  };
}

export function getWebPolicy(): WebPolicy {
  return state;
}

export function subscribeWebPolicy(fn: () => void): () => void {
  listeners.add(fn);
  return () => { listeners.delete(fn); };
}

/** Hello / workspace switch: bind identity and replace policy. */
export function bindWebPolicy(workspace: string, policy?: Partial<WebPolicy>): WebPolicy {
  const ws = workspaceKey(workspace) || workspace;
  state = {
    enabled: Boolean(policy?.enabled),
    admin_allows: policy?.admin_allows !== undefined ? Boolean(policy.admin_allows) : true,
    requested: policy?.requested !== undefined ? Boolean(policy.requested) : policy?.requested,
    workspace: ws || undefined,
  };
  bump();
  notify();
  return state;
}

export function applyWebPolicy(next: Partial<WebPolicy>): WebPolicy {
  const incoming = workspaceKey(next.workspace);
  const current = workspaceKey(state.workspace);
  if (incoming && current && incoming !== current) {
    return state;
  }
  state = policyFrom(next, state.workspace);
  bump();
  notify();
  return state;
}

function beginRequest(explicitWs?: string): { epoch: number; workspace?: string } {
  // Later in-flight save/load wins over an earlier one that has not
  // applied yet. bind/apply also bump, so a hello or remote event
  // invalidates older HTTP round-trips.
  bump();
  return {
    epoch,
    workspace: workspaceKey(explicitWs) || workspaceKey(state.workspace) || undefined,
  };
}

function isStale(req: { epoch: number; workspace?: string }): boolean {
  if (req.epoch !== epoch) return true;
  const now = workspaceKey(state.workspace);
  const was = workspaceKey(req.workspace);
  if (was && now && was !== now) return true;
  return false;
}

function scopedGetUrl(workspace?: string): string {
  const ws = workspaceKey(workspace);
  if (!ws) return "/api/web-policy";
  return `/api/web-policy?workspace=${encodeURIComponent(ws)}`;
}

export async function loadWebPolicy(workspace?: string): Promise<WebPolicy> {
  const req = beginRequest(workspace);
  const r = await fetch(scopedGetUrl(req.workspace));
  const body = (await r.json().catch(() => ({}))) as WebPolicy;
  if (isStale(req)) return getWebPolicy();
  if (!r.ok) return getWebPolicy();
  const bodyWs = workspaceKey(body.workspace);
  if (bodyWs && req.workspace && bodyWs !== req.workspace) return getWebPolicy();
  return applyWebPolicy({ ...body, workspace: req.workspace || body.workspace });
}

export async function setWebPolicy(enabled: boolean): Promise<WebPolicy> {
  const req = beginRequest();
  const payload: Record<string, unknown> = { enabled };
  if (req.workspace) payload.workspace = req.workspace;
  const r = await fetch("/api/web-policy", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const body = (await r.json().catch(() => ({}))) as WebPolicy & { error?: string };
  // Stale success/error: keep whatever is current. Only a still-current
  // failed save reports to the caller, and never applies error-body policy.
  if (isStale(req)) return getWebPolicy();
  const bodyWs = workspaceKey(body.workspace);
  if (bodyWs && req.workspace && bodyWs !== req.workspace) return getWebPolicy();
  if (!r.ok) {
    const err = new Error(body.error || `HTTP ${r.status}`);
    (err as Error & { policy: WebPolicy }).policy = getWebPolicy();
    throw err;
  }
  return applyWebPolicy({
    enabled: Boolean(body.enabled),
    admin_allows: body.admin_allows !== undefined ? Boolean(body.admin_allows) : state.admin_allows,
    requested: body.requested,
    workspace: req.workspace || body.workspace,
  });
}

export function useWebPolicy(): WebPolicy {
  const [s, setS] = useState<WebPolicy>(state);
  useEffect(() => subscribeWebPolicy(() => setS({ ...getWebPolicy() })), []);
  return s;
}
