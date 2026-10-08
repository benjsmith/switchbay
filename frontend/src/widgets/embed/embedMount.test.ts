import assert from "node:assert/strict";
import { test } from "node:test";
import {
  documentDir,
  embedFetchShimScript,
  embedHostShimScript,
  extractScripts,
  isSwitchbayReservedApi,
  mapStatusBanner,
  prepareEmbedHtml,
  rewriteAssetUrl,
  rewriteHtmlUrls,
} from "./embedMount.ts";

test("documentDir resolves trailing and file paths", () => {
  assert.equal(documentDir("/embed/ce", "/"), "/embed/ce/");
  assert.equal(documentDir("/embed/ce", "/observer/"), "/embed/ce/observer/");
  assert.equal(documentDir("/embed/okstratr", "/observer/index.html"), "/embed/okstratr/observer/");
});

test("rewriteAssetUrl maps relative, root-relative, and loopback", () => {
  assert.equal(
    rewriteAssetUrl("static/main.js", "/embed/ce", "/"),
    "/embed/ce/static/main.js",
  );
  assert.equal(
    rewriteAssetUrl("observer.css", "/embed/okstratr", "/observer/"),
    "/embed/okstratr/observer/observer.css",
  );
  assert.equal(
    rewriteAssetUrl("/api/graph", "/embed/ce", "/"),
    "/embed/ce/api/graph",
  );
  assert.equal(
    rewriteAssetUrl("http://127.0.0.1:8766/static/x.js", "/embed/ce", "/"),
    "/embed/ce/static/x.js",
  );
  assert.equal(
    rewriteAssetUrl("https://fonts.googleapis.com/css", "/embed/ce", "/"),
    "https://fonts.googleapis.com/css",
  );
  assert.equal(
    rewriteAssetUrl("data:image/png;base64,xx", "/embed/ce", "/"),
    "data:image/png;base64,xx",
  );
  assert.equal(
    rewriteAssetUrl("/embed/ce/static/main.js", "/embed/ce", "/"),
    "/embed/ce/static/main.js",
  );
  assert.equal(
    rewriteAssetUrl("../vendor/d3.js", "/embed/ce", "/static/app/"),
    "/embed/ce/static/vendor/d3.js",
  );
});

test("rewriteHtmlUrls rewrites src/href/srcset and style url()", () => {
  const html = `
<link rel="stylesheet" href="static/main.css">
<img srcset="a.png 1x, /b.png 2x">
<div style="background:url('img/bg.png')"></div>
<script src="static/main.js"></script>
`;
  const out = rewriteHtmlUrls(html, "/embed/ce", "/");
  assert.match(out, /href="\/embed\/ce\/static\/main\.css"/);
  assert.match(out, /src="\/embed\/ce\/static\/main\.js"/);
  assert.match(out, /srcset="\/embed\/ce\/a\.png 1x, \/embed\/ce\/b\.png 2x"/);
  assert.match(out, /url\('\/embed\/ce\/img\/bg\.png'\)/);
});

test("extractScripts preserves order and module/classic", () => {
  const html = `
<script src="/embed/ce/a.js"></script>
<script type="module">import "/x";</script>
<script>window.BOOT=1;</script>
`;
  const { htmlWithoutScripts, scripts } = extractScripts(html);
  assert.equal(scripts.length, 3);
  assert.equal(scripts[0].type, "classic");
  assert.equal(scripts[0].src, "/embed/ce/a.js");
  assert.equal(scripts[1].type, "module");
  assert.equal(scripts[1].content, 'import "/x";');
  assert.equal(scripts[2].content, "window.BOOT=1;");
  assert.equal(htmlWithoutScripts.includes("<script"), false);
});

test("prepareEmbedHtml yields markup + rewritten script srcs", () => {
  const html = `<!DOCTYPE html><html><head>
<link rel="stylesheet" href="static/main.css">
</head><body>
<div id="graph"></div>
<script src="static/main.js"></script>
</body></html>`;
  const { markup, scripts } = prepareEmbedHtml(html, "/embed/ce", "/");
  assert.match(markup, /id="graph"/);
  assert.match(markup, /href="\/embed\/ce\/static\/main\.css"/);
  assert.equal(scripts.length, 1);
  assert.equal(scripts[0].src, "/embed/ce/static/main.js");
  assert.equal(markup.includes("<script"), false);
});

test("mapStatusBanner: starting suppresses 502 and blocks mount", () => {
  const b = mapStatusBanner("ce", {
    ce: { state: "starting", detail: "booting" },
    okstratr: { state: "healthy" },
    wiki_build: { state: "idle", pages: null, detail: "" },
  });
  assert.equal(b.kind, "starting");
  assert.equal(b.allowMount, false);
  assert.equal(b.suppressFetchError, true);
  assert.match(b.label, /starting/i);
});

test("mapStatusBanner: stopped treated as starting wait chrome", () => {
  const b = mapStatusBanner("okstratr", {
    ce: { state: "healthy" },
    okstratr: { state: "stopped" },
    wiki_build: { state: "idle" },
  });
  assert.equal(b.kind, "starting");
  assert.equal(b.suppressFetchError, true);
});

test("mapStatusBanner: unhealthy", () => {
  const b = mapStatusBanner("ce", {
    ce: { state: "unhealthy", detail: "exit 1" },
    wiki_build: { state: "idle" },
  });
  assert.equal(b.kind, "unhealthy");
  assert.equal(b.allowMount, false);
  assert.match(b.label, /unhealthy/);
});

test("mapStatusBanner: live vs building wiki", () => {
  const live = mapStatusBanner("ce", {
    ce: { state: "healthy" },
    wiki_build: { state: "idle" },
  });
  assert.equal(live.kind, "live");
  assert.equal(live.allowMount, true);

  const building = mapStatusBanner("ce", {
    ce: { state: "healthy" },
    wiki_build: { state: "building", pages: 3 },
  });
  assert.equal(building.kind, "building_wiki");
  assert.equal(building.allowMount, true);
  assert.match(building.label, /wiki/i);
});

test("isSwitchbayReservedApi protects control-plane paths", () => {
  assert.equal(isSwitchbayReservedApi("/api/settings"), true);
  assert.equal(isSwitchbayReservedApi("/api/core-skills/status"), true);
  assert.equal(isSwitchbayReservedApi("/api/graph/data"), true);
  assert.equal(isSwitchbayReservedApi("/api/workspaces/switch"), true);
  assert.equal(isSwitchbayReservedApi("/api/tree"), true);
  assert.equal(isSwitchbayReservedApi("/api/llm/providers"), true);
  // Settings power controls must stay on the Switchbay daemon while an
  // embed fetch shim is installed (otherwise Restart/Update toast "not found"
  // from okstratr/CE via /embed/*/api/restart).
  assert.equal(isSwitchbayReservedApi("/api/restart"), true);
  assert.equal(isSwitchbayReservedApi("/api/update"), true);
  assert.equal(isSwitchbayReservedApi("/api/update/check"), true);
  assert.equal(isSwitchbayReservedApi("/api/quit"), true);
  assert.equal(isSwitchbayReservedApi("/api/versions"), true);
  assert.equal(isSwitchbayReservedApi("/api/admin-policy"), true);
  // Same class: other Switchbay-owned chrome/settings paths that Settings or
  // the shell call while a Graph/Agents embed fetch shim is installed.
  assert.equal(isSwitchbayReservedApi("/api/fs/reveal"), true);
  assert.equal(isSwitchbayReservedApi("/api/file"), true);
  assert.equal(isSwitchbayReservedApi("/api/file-routes"), true);
  assert.equal(isSwitchbayReservedApi("/api/tabs/terminal"), true);
  assert.equal(isSwitchbayReservedApi("/api/runs/active"), true);
  assert.equal(isSwitchbayReservedApi("/api/permission/pending"), true);
  assert.equal(isSwitchbayReservedApi("/api/okstratr/harness"), true);
  assert.equal(isSwitchbayReservedApi("/api/localllm/status"), true);
  assert.equal(isSwitchbayReservedApi("/api/easter/thrusters"), true);
  assert.equal(isSwitchbayReservedApi("/api/report-packages/open"), true);
  assert.equal(isSwitchbayReservedApi("/api/micro-edits/model"), true);
  assert.equal(isSwitchbayReservedApi("/api/walkthrough/status"), true);
  assert.equal(isSwitchbayReservedApi("/api/share/status"), true);
  assert.equal(isSwitchbayReservedApi("/api/web-policy"), true);
  // Skill-owned paths stay remappable onto /embed/*
  assert.equal(isSwitchbayReservedApi("/api/page?path=x"), false);
  assert.equal(isSwitchbayReservedApi("/api/vault/foo"), false);
  assert.equal(isSwitchbayReservedApi("/api/desk/status"), false);
  assert.equal(isSwitchbayReservedApi("/api/workspace/select"), false);
});

test("embedFetchShimScript rewrites data.json onto public base", () => {
  const shim = embedFetchShimScript("/embed/ce");
  assert.equal(shim.type, "classic");
  assert.ok(shim.content);
  assert.match(shim.content!, /\/embed\/ce/);
  assert.match(shim.content!, /data\.json/);
  // Evaluate shim in a minimal fetch stub.
  const calls: string[] = [];
  const g = globalThis as typeof globalThis & {
    window: any;
    fetch: typeof fetch;
  };
  g.window = g;
  g.fetch = (async (input: any) => {
    calls.push(typeof input === "string" ? input : String(input?.url));
    return new Response("{}");
  }) as typeof fetch;
  // eslint-disable-next-line no-eval
  eval(shim.content!);
  void g.fetch("data.json");
  void g.fetch("data.json?t=1");
  void g.fetch("/api/page?path=notes/x.md");
  void g.fetch("/embed/ce/already");
  void g.fetch("/api/settings");
  void g.fetch("/api/core-skills/status");
  void g.fetch("/api/tree");
  void g.fetch("/api/llm/providers");
  void g.fetch("/api/restart", { method: "POST" });
  void g.fetch("/api/update", { method: "POST" });
  void g.fetch("/api/quit", { method: "POST" });
  void g.fetch("/api/fs/reveal", { method: "POST" });
  void g.fetch("/api/runs/active");
  void g.fetch("/api/easter/thrusters", { method: "POST" });
  void g.fetch("/api/okstratr/harness");
  assert.equal(calls[0], "/embed/ce/data.json");
  assert.equal(calls[1], "/embed/ce/data.json?t=1");
  assert.equal(calls[2], "/embed/ce/api/page?path=notes/x.md");
  assert.equal(calls[3], "/embed/ce/already");
  assert.equal(calls[4], "/api/settings");
  assert.equal(calls[5], "/api/core-skills/status");
  assert.equal(calls[6], "/api/tree");
  assert.equal(calls[7], "/api/llm/providers");
  assert.equal(calls[8], "/api/restart");
  assert.equal(calls[9], "/api/update");
  assert.equal(calls[10], "/api/quit");
  assert.equal(calls[11], "/api/fs/reveal");
  assert.equal(calls[12], "/api/runs/active");
  assert.equal(calls[13], "/api/easter/thrusters");
  assert.equal(calls[14], "/api/okstratr/harness");
  // Release restores fetch
  assert.equal(typeof g.window.__syEmbedReleaseFetch, "function");
  g.window.__syEmbedReleaseFetch();
  assert.equal(g.window.__syEmbedFetchBase, null);
});

test("embedHostShimScript marks syHost and guards body.innerHTML", () => {
  const shim = embedHostShimScript('[data-sy-embed-root="1"]');
  assert.equal(shim.type, "classic");
  assert.match(shim.content!, /syHost/);
  assert.match(shim.content!, /innerHTML/);
});
