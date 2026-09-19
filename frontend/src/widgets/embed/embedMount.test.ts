import assert from "node:assert/strict";
import { test } from "node:test";
import {
  documentDir,
  extractScripts,
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
