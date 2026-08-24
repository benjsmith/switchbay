/**
 * Host adapter for workbench widgets that currently assume the PWA
 * (`fetch("/api/...")`, `CustomEvent`, hash navigation).
 *
 * The VS Code plugin must not talk to `:8765`. Widgets that we reuse
 * in webviews should call this interface; the PWA implements it with
 * REST/WS, the plugin with `acquireVsCodeApi().postMessage`.
 *
 * This file is the contract. Wiring GraphTab / AgentDashboard / preview
 * onto it is a later spike step — do not fetch the daemon from a
 * plugin webview in the meantime.
 */

export type GraphNodeRef = {
  id: string;
  path: string;
  title?: string;
  type?: string;
};

export type RunSnapshot = {
  id: string;
  status: string;
  title?: string;
  payload?: unknown;
};

export type WorkbenchHost = {
  graphData(): Promise<unknown | null>;
  openPage(ref: GraphNodeRef): void;
  openPreview(ref: GraphNodeRef): void;
  revealInExplorer(path: string): void;
  runSlash(command: string): void;
  watchRuns(cb: (runs: RunSnapshot[]) => void): () => void;
};

declare global {
  interface Window {
    syHost?: WorkbenchHost;
  }
}

export function getHost(): WorkbenchHost | null {
  return window.syHost ?? null;
}
