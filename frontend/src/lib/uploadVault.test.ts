import assert from "node:assert/strict";
import { test } from "node:test";
import {
  INGEST_PREF_KEY,
  UPLOAD_VAULT_URL,
  buildUploadForm,
  describeUploadResult,
  loadIngestPref,
  saveIngestPref,
  uploadToVault,
} from "./uploadVault.ts";

function memStore(init: Record<string, string> = {}) {
  const m = new Map(Object.entries(init));
  return {
    getItem: (k: string) => (m.has(k) ? (m.get(k) as string) : null),
    setItem: (k: string, v: string) => void m.set(k, v),
    map: m,
  };
}

const files = () => [
  new File(["hello"], "a.txt", { type: "text/plain" }),
  new File(["# b"], "b c.md", { type: "text/markdown" }),
];

test("ingest checkbox defaults off and remembers the last choice", () => {
  const store = memStore();
  assert.equal(loadIngestPref(store), false);
  saveIngestPref(true, store);
  assert.equal(store.map.get(INGEST_PREF_KEY), "1");
  assert.equal(loadIngestPref(store), true);
  saveIngestPref(false, store);
  assert.equal(loadIngestPref(store), false);
  assert.equal(loadIngestPref(null), false);
});

test("form carries every file as `file` plus the ingest flag", () => {
  for (const ingest of [true, false]) {
    const form = buildUploadForm(files(), ingest);
    assert.equal(form.get("ingest"), ingest ? "true" : "false");
    const sent = form.getAll("file") as File[];
    assert.deepEqual(sent.map((f) => f.name), ["a.txt", "b c.md"]);
  }
});

test("uploadToVault posts the form to the daemon route", async () => {
  let seen: { url: string; init: RequestInit } | null = null;
  const fake = (async (url: string, init: RequestInit) => {
    seen = { url, init };
    return new Response(JSON.stringify({ ok: true, saved: ["a.txt", "b_c.md"] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  }) as unknown as typeof fetch;
  const r = await uploadToVault(files(), true, fake);
  assert.deepEqual(r.saved, ["a.txt", "b_c.md"]);
  assert.ok(seen);
  const s = seen as { url: string; init: RequestInit };
  assert.equal(s.url, UPLOAD_VAULT_URL);
  assert.equal(s.init.method, "POST");
  const body = s.init.body as FormData;
  assert.equal(body.get("ingest"), "true");
  assert.equal(body.getAll("file").length, 2);
});

test("uploadToVault surfaces the server error", async () => {
  const fake = (async () =>
    new Response(JSON.stringify({ error: "file too large (>50 MB)" }), { status: 413 })
  ) as unknown as typeof fetch;
  await assert.rejects(uploadToVault(files(), false, fake), /too large/);
});

test("result text reflects the ingest backend", () => {
  assert.deepEqual(describeUploadResult({ saved: ["a.txt"] }), {
    text: "Uploaded a.txt to vault/raw/", err: false, openRunId: null,
  });
  const runs = [{ file: "a.txt", run_id: "run-1", vault_path: "vault/raw/a.txt" }];
  assert.equal(
    describeUploadResult({
      saved: ["a.txt", "b.md"],
      ingest: { requested: true, backend: "local_ingest", queued: true, runs },
    }).text,
    "Uploaded 2 files to vault/raw/; ingest queued",
  );
  assert.deepEqual(
    describeUploadResult({
      saved: ["a.txt"],
      ingest: { requested: true, backend: "agent", queued: true, runs },
    }).openRunId,
    "run-1",
  );
  const none = describeUploadResult({
    saved: ["a.txt"],
    ingest: { requested: true, backend: "none", queued: false, runs: [], message: "no backend" },
  });
  assert.equal(none.text, "no backend");
  assert.equal(none.err, true);
});
