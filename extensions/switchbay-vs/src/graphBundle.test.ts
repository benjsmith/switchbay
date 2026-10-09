import * as assert from "node:assert/strict";
import * as fs from "node:fs";
import * as os from "node:os";
import * as path from "node:path";
import { after, test } from "node:test";

import { answerCeApi, bundleFresh, ceViewerAvailable, safeEditablePage, type ApiHost } from "./graphBundle";

const made: string[] = [];
after(() => {
  for (const d of made) fs.rmSync(d, { recursive: true, force: true });
});

function tmp(): string {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "sbvs-graph-"));
  made.push(d);
  return d;
}

function age(p: string, seconds: number): void {
  const t = fs.statSync(p).mtime.getTime() / 1000 - seconds;
  fs.utimesSync(p, t, t);
}

function ageTree(dir: string, seconds: number): void {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) ageTree(p, seconds);
    age(p, seconds);
  }
  age(dir, seconds);
}

function setup(): { wiki: string; bundle: string } {
  const root = tmp();
  const wiki = path.join(root, "wiki");
  fs.mkdirSync(path.join(wiki, "concepts"), { recursive: true });
  fs.mkdirSync(path.join(wiki, "notes"), { recursive: true });
  fs.writeFileSync(path.join(wiki, "concepts", "a.md"), "# A\n");
  fs.writeFileSync(path.join(wiki, "notes", "n.md"), "# N\n");
  const bundle = path.join(root, "bundle");
  fs.mkdirSync(path.join(bundle, "static"), { recursive: true });
  fs.writeFileSync(path.join(bundle, "static", "embed.js"), "");
  fs.writeFileSync(path.join(bundle, "data.json"), '{"nodes":[]}');
  // Built 100 s ago from a wiki last touched 200 s ago.
  age(path.join(bundle, "data.json"), 100);
  ageTree(wiki, 200);
  return { wiki, bundle };
}

test("CE counts as installed only with the bundle builder and embeddable viewer", () => {
  const ce = tmp();
  assert.equal(ceViewerAvailable(undefined), false);
  assert.equal(ceViewerAvailable(ce), false);
  fs.mkdirSync(path.join(ce, "scripts"));
  fs.writeFileSync(path.join(ce, "scripts", "wiki_render.py"), "");
  assert.equal(ceViewerAvailable(ce), false);
  fs.mkdirSync(path.join(ce, "template", "wiki-view", "static"), { recursive: true });
  fs.writeFileSync(path.join(ce, "template", "wiki-view", "static", "embed.js"), "");
  assert.equal(ceViewerAvailable(ce), true);
});

test("bundle goes stale on page edits and deletions", () => {
  const { wiki, bundle } = setup();
  assert.equal(bundleFresh(bundle, wiki), true);
  fs.writeFileSync(path.join(wiki, "concepts", "a.md"), "# A2\n");
  assert.equal(bundleFresh(bundle, wiki), false);
  ageTree(wiki, 300);
  assert.equal(bundleFresh(bundle, wiki), true);
  fs.unlinkSync(path.join(wiki, "concepts", "a.md"));
  assert.equal(bundleFresh(bundle, wiki), false);
});

test("bundle goes stale when the graph db or a refresh mark is newer", () => {
  const { wiki, bundle } = setup();
  const db = path.join(path.dirname(wiki), "graph.kuzu");
  fs.writeFileSync(db, "");
  age(db, 300);
  assert.equal(bundleFresh(bundle, wiki, [db, path.join(wiki, "absent")]), true);
  fs.writeFileSync(db, "x");
  assert.equal(bundleFresh(bundle, wiki, [db]), false);
  age(db, 300);
  assert.equal(bundleFresh(bundle, wiki, [db], Date.now() + 1000), false);
});

test("a bundle without the embeddable viewer is never fresh", () => {
  const { wiki, bundle } = setup();
  fs.unlinkSync(path.join(bundle, "static", "embed.js"));
  assert.equal(bundleFresh(bundle, wiki), false);
});

test("only notes/ and todos/ markdown inside wiki/ is editable", () => {
  const { wiki } = setup();
  assert.equal(safeEditablePage(wiki, "notes/n.md"), path.join(wiki, "notes", "n.md"));
  assert.equal(safeEditablePage(wiki, "todos/new.md"), path.join(wiki, "todos", "new.md"));
  for (const bad of ["concepts/a.md", "notes/../concepts/a.md", "../x.md", "notes/x.txt", "notes/", "/etc/passwd", "notes\\x.md", ""]) {
    assert.throws(() => safeEditablePage(wiki, bad), bad);
  }
});

test("CE API calls are answered from disk", async () => {
  const { wiki } = setup();
  let rebuilt = 0;
  const host: ApiHost = {
    wikiDir: wiki,
    data: async () => '{"nodes":[{"id":"a"}]}',
    rebuild: async () => { rebuilt++; },
    history: async () => ({ events: [1] }),
  };
  const data = await answerCeApi(host, "GET", "/data.json?t=1");
  assert.equal(data.status, 200);
  assert.equal(JSON.parse(data.body).nodes[0].id, "a");

  const read = await answerCeApi(host, "GET", "/api/page?path=notes%2Fn.md");
  assert.deepEqual(JSON.parse(read.body), { path: "notes/n.md", content: "# N\n" });

  const save = await answerCeApi(host, "POST", "/api/page", JSON.stringify({ path: "notes/n.md", content: "# N2" }));
  assert.equal(save.status, 200);
  assert.equal(fs.readFileSync(path.join(wiki, "notes", "n.md"), "utf8"), "# N2\n");
  assert.equal(rebuilt, 1);

  const denied = await answerCeApi(host, "POST", "/api/page", JSON.stringify({ path: "concepts/a.md", content: "x" }));
  assert.equal(denied.status, 400);
  assert.equal(fs.readFileSync(path.join(wiki, "concepts", "a.md"), "utf8"), "# A\n");
  assert.equal(rebuilt, 1);

  assert.equal((await answerCeApi(host, "GET", "/api/page?path=notes%2Fmissing.md")).status, 404);
  assert.deepEqual(JSON.parse((await answerCeApi(host, "GET", "/api/curation/history")).body), { events: [1] });
  assert.equal((await answerCeApi(host, "POST", "/api/split", "{}")).status, 404);

  const none = await answerCeApi({ ...host, data: async () => null }, "GET", "/data.json");
  assert.equal(none.status, 404);
});
