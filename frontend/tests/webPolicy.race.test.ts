import assert from "node:assert/strict";
import {
  applyWebPolicy,
  bindWebPolicy,
  getWebPolicy,
  loadWebPolicy,
  setWebPolicy,
} from "../src/lib/webPolicy.ts";

type FetchCall = { url: string; method: string; body?: string };
const calls: FetchCall[] = [];
let pending: Array<(r: { ok: boolean; status: number; json: () => Promise<unknown> }) => void> = [];

function jsonResp(ok: boolean, body: unknown, status = ok ? 200 : 500) {
  return { ok, status, json: async () => body };
}

globalThis.fetch = ((url: string | URL, init?: RequestInit) => {
  const href = String(url);
  const method = String(init?.method || "GET").toUpperCase();
  calls.push({ url: href, method, body: typeof init?.body === "string" ? init.body : undefined });
  return new Promise((resolve) => {
    pending.push(resolve);
  });
}) as typeof fetch;

function flush(ok: boolean, body: unknown, status?: number) {
  const resolve = pending.shift();
  assert.ok(resolve, "expected a pending fetch");
  resolve(jsonResp(ok, body, status));
}

async function tick() {
  await Promise.resolve();
  await Promise.resolve();
}

{
  calls.length = 0;
  pending = [];
  bindWebPolicy("/ws-a", { enabled: false, admin_allows: true });
  const save = setWebPolicy(true);
  bindWebPolicy("/ws-b", { enabled: false, admin_allows: true });
  flush(true, { enabled: true, admin_allows: true, workspace: "/ws-a" });
  await save;
  assert.equal(getWebPolicy().enabled, false, "stale save from previous workspace overwrote current policy");
  assert.equal(getWebPolicy().workspace, "/ws-b");
  const posted = JSON.parse(calls[0]!.body || "{}") as { workspace?: string };
  assert.equal(posted.workspace, "/ws-a", "save must target originating workspace");
}

{
  calls.length = 0;
  pending = [];
  bindWebPolicy("/ws-a", { enabled: false, admin_allows: true });
  const save = setWebPolicy(true);
  bindWebPolicy("/ws-b", { enabled: true, admin_allows: true });
  flush(false, { error: "save failed", enabled: false, workspace: "/ws-a" }, 500);
  const after = await save;
  assert.equal(after.enabled, true, "stale failed save restored old policy over current workspace");
  assert.equal(getWebPolicy().enabled, true);
  assert.equal(getWebPolicy().workspace, "/ws-b");
}

{
  calls.length = 0;
  pending = [];
  bindWebPolicy("/ws-a", { enabled: false, admin_allows: true });
  const save = setWebPolicy(true);
  applyWebPolicy({ enabled: true, admin_allows: true, workspace: "/ws-a" });
  flush(true, { enabled: false, admin_allows: true, workspace: "/ws-a" });
  await save;
  assert.equal(getWebPolicy().enabled, true, "stale save success must not clobber a newer remote policy");
}

{
  calls.length = 0;
  pending = [];
  bindWebPolicy("/ws-a", { enabled: false, admin_allows: true });
  const load = loadWebPolicy("/ws-a");
  bindWebPolicy("/ws-b", { enabled: true, admin_allows: true });
  flush(true, { enabled: false, admin_allows: true, workspace: "/ws-a" });
  await load;
  assert.equal(getWebPolicy().enabled, true, "stale load must not clobber the switched workspace");
  assert.ok(calls[0]!.url.includes("workspace="), "load must scope GET to originating workspace");
  assert.ok(decodeURIComponent(calls[0]!.url).includes("/ws-a"));
}

{
  calls.length = 0;
  pending = [];
  bindWebPolicy("/ws-a", { enabled: true, admin_allows: true });
  const save = setWebPolicy(false);
  flush(false, { error: "nope" }, 500);
  let threw = false;
  try {
    await save;
  } catch {
    threw = true;
  }
  assert.equal(threw, true);
  assert.equal(getWebPolicy().enabled, true, "failed save without a valid newer policy must keep current state");
}

{
  calls.length = 0;
  pending = [];
  bindWebPolicy("/ws-a", { enabled: false, admin_allows: true });
  const first = setWebPolicy(true);
  const second = setWebPolicy(false);
  flush(true, { enabled: true, admin_allows: true, workspace: "/ws-a" });
  await first;
  flush(true, { enabled: false, admin_allows: true, workspace: "/ws-a" });
  await second;
  assert.equal(getWebPolicy().enabled, false, "later in-flight save must win over an earlier one");
  assert.equal(JSON.parse(calls[0]!.body || "{}").workspace, "/ws-a");
  assert.equal(JSON.parse(calls[1]!.body || "{}").workspace, "/ws-a");
}

{
  calls.length = 0;
  pending = [];
  bindWebPolicy("/ws-a", { enabled: false, admin_allows: true });
  const load = loadWebPolicy("/ws-a");
  applyWebPolicy({ enabled: true, admin_allows: true, workspace: "/ws-a" });
  flush(true, { enabled: false, admin_allows: true, workspace: "/ws-a" });
  await load;
  assert.equal(getWebPolicy().enabled, true, "stale load must not clobber a newer remote policy");
}

await tick();
console.log("webPolicy.race.test.ts ok");
