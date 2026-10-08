import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { renderSidebarShell, workspaceLabel } from "./ceSidebarHeader.ts";

const shell = readFileSync(new URL("./ceSidebarShell.html", import.meta.url), "utf8");

function headerName(html: string): string {
  const m = html.match(/<span class="workspace-name">([^<]*)<\/span>/);
  assert.ok(m, "sidebar shell keeps a .workspace-name header");
  return m[1];
}

test("sidebar shell still carries the {{WORKSPACE}} placeholder CE uses", () => {
  assert.match(shell, /\{\{WORKSPACE\}\}/);
});

test("mounted header shows the workspace name, never the raw placeholder", () => {
  const html = renderSidebarShell(shell, { workspace: "/Users/ben/Workspaces/ml-walkthrough" });
  assert.equal(headerName(html), "ml-walkthrough");
  assert.doesNotMatch(html, /\{\{WORKSPACE\}\}/);
});

test("trailing slashes and Windows paths resolve to the folder name", () => {
  assert.equal(workspaceLabel({ workspace: "/tmp/ws/research/" }), "research");
  assert.equal(workspaceLabel({ workspace: "C:\\Users\\ben\\notes" }), "notes");
});

test("missing workspace falls back to a neutral label, not the placeholder", () => {
  for (const data of [null, {}, { workspace: "" }, { workspace: 42 }]) {
    const html = renderSidebarShell(shell, data);
    assert.equal(headerName(html), "workspace");
    assert.doesNotMatch(html, /\{\{WORKSPACE\}\}/);
  }
});

test("workspace names are inserted as text, not markup", () => {
  const html = renderSidebarShell(shell, { workspace: "/tmp/<b>x</b>" });
  assert.doesNotMatch(html, /<b>x/);
  assert.doesNotMatch(html, /\{\{WORKSPACE\}\}/);
});
