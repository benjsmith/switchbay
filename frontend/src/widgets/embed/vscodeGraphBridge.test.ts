import assert from "node:assert/strict";
import { test } from "node:test";

import {
  VSCODE_CE_API, bridgedPath, ceThemeFor, installFetchBridge, nodeRef,
  searchHitPaths, vscodeCeApi, wikiFilePath, type BridgeRequest,
} from "./vscodeGraphBridge.ts";

test("CE API paths map onto the virtual origin and back", () => {
  assert.equal(vscodeCeApi("/data.json"), `${VSCODE_CE_API}/data.json`);
  assert.equal(vscodeCeApi("api/page?path=a.md"), `${VSCODE_CE_API}/api/page?path=a.md`);
  assert.equal(bridgedPath(`${VSCODE_CE_API}/api/page?path=a.md`), "/api/page?path=a.md");
  assert.equal(bridgedPath("https://example.com/ce/data.json"), null);
  assert.equal(bridgedPath(`${VSCODE_CE_API}evil/x`), null);
});

test("bridged fetches round-trip through postMessage; others hit the network", async () => {
  const sent: BridgeRequest[] = [];
  const native: string[] = [];
  const target = {
    fetch: (async (input: RequestInfo | URL) => {
      native.push(String(input));
      return new Response("net");
    }) as typeof fetch,
  };
  const deliver = installFetchBridge(target, (m) => sent.push(m));

  const pending = target.fetch(`${VSCODE_CE_API}/api/page`, {
    method: "post",
    body: JSON.stringify({ path: "notes/a.md", content: "x" }),
  });
  await new Promise((r) => setTimeout(r, 0));
  assert.equal(sent.length, 1);
  assert.deepEqual(
    { method: sent[0].method, path: sent[0].path, body: sent[0].body },
    { method: "POST", path: "/api/page", body: '{"path":"notes/a.md","content":"x"}' },
  );
  assert.equal(deliver({ type: "api-result", id: 999, status: 200, body: "" }), false);
  assert.equal(deliver({ type: "api-result", id: sent[0].id, status: 200, body: '{"ok":true}' }), true);
  const res = await pending;
  assert.equal(res.status, 200);
  assert.deepEqual(await res.json(), { ok: true });

  const other = await target.fetch("https://example.com/x");
  assert.equal(await other.text(), "net");
  assert.deepEqual(native, ["https://example.com/x"]);
  assert.equal(sent.length, 1);
});

test("a bridged fetch the host never answers times out instead of hanging", async () => {
  const target = { fetch: (async () => new Response("")) as typeof fetch };
  installFetchBridge(target, () => {}, 10);
  const res = await target.fetch(`${VSCODE_CE_API}/data.json`);
  assert.equal(res.status, 504);
});

test("binary uploads are refused in the bridge", async () => {
  const sent: BridgeRequest[] = [];
  const target = { fetch: (async () => new Response("")) as typeof fetch };
  installFetchBridge(target, (m) => sent.push(m));
  const res = await target.fetch(`${VSCODE_CE_API}/api/upload-vault`, {
    method: "POST", body: new Uint8Array([1, 2]),
  });
  assert.equal(res.status, 501);
  assert.equal(sent.length, 0);
});

test("search hits mark wiki pages and the vault files behind them", () => {
  const data = {
    nodes: [
      { id: "a", path: "concepts/a.md", title: "A" },
      { id: "b", path: "wiki/projects/b.md", title: "B" },
    ],
    pages: {
      a: { properties: { sources: ["20260101-paper.pdf", "https://x.org/y.pdf", "wiki/projects/b.md"] } },
      b: { properties: { source: "vault/raw/b.md" } },
    },
  };
  assert.deepEqual(searchHitPaths(data, ["a", "b"]), {
    paths: ["wiki/concepts/a.md", "wiki/projects/b.md"],
    sourcePaths: ["vault/20260101-paper.pdf", "vault/raw/b.md"],
  });
  assert.deepEqual(searchHitPaths(data, []), { paths: [], sourcePaths: [] });
});

test("node refs fall back to page metadata, then the id", () => {
  const data = { nodes: [], pages: { p: { path: "notes/p.md", title: "P", type: "note" } } };
  assert.deepEqual(nodeRef(data, "p"), { id: "p", path: "notes/p.md", title: "P", type: "note" });
  assert.deepEqual(nodeRef(null, "q"), { id: "q", path: "q", title: "q", type: undefined });
  assert.equal(wikiFilePath("./concepts/x.md"), "wiki/concepts/x.md");
  assert.equal(wikiFilePath("vault/a.pdf"), "vault/a.pdf");
});

test("VS Code theme classes pick CE's light or dark theme", () => {
  assert.equal(ceThemeFor("vscode-light"), "light");
  assert.equal(ceThemeFor("vscode-high-contrast-light foo"), "light");
  assert.equal(ceThemeFor("vscode-dark"), "dark");
  assert.equal(ceThemeFor("vscode-high-contrast"), "dark");
});
