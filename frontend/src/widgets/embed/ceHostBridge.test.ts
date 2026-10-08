import assert from "node:assert/strict";
import { test } from "node:test";

// ceHostBridge reads `window` lazily; give node a minimal one.
(globalThis as unknown as { window: unknown }).window = globalThis;

const {
  guardCeModal, isCeSplitUrl, toSwitchbaySplitBody,
} = await import("./ceHostBridge.ts");

test("CE modal bodies are sanitized on open (init, refresh and re-open)", () => {
  const rendered: string[] = [];
  const pages: Record<string, { body_html: string }> = {};
  const modal = {
    init(data: { pages: typeof pages }) { Object.assign(pages, data.pages); },
    refresh(data: { pages: typeof pages }) { Object.assign(pages, data.pages); },
    open(id: string) { rendered.push(pages[id]?.body_html ?? ""); return true; },
  };
  (globalThis as unknown as { Modal: typeof modal }).Modal = modal;
  const clean = (h: string) => h.replace(/ onerror=[^>]*/g, "").replace(/<script>.*?<\/script>/g, "");
  assert.equal(guardCeModal(clean), true);

  const data = { pages: { a: { body_html: '<p>x<img src=x onerror=alert(1)></p><script>alert(2)</script>' } } };
  modal.init(data);
  modal.open("a");
  assert.equal(rendered[0], "<p>x<img src=x></p>");

  const fresh = { pages: { a: { body_html: "<p>y<script>alert(3)</script></p>" } } };
  modal.refresh(fresh);
  modal.open("a");
  assert.equal(rendered[1], "<p>y</p>");

  // Guarding twice must not double-wrap.
  assert.equal(guardCeModal(clean), true);
  modal.open("a");
  assert.equal(rendered[2], "<p>y</p>");
});

test("split URL matcher covers raw and embed-prefixed paths only", () => {
  assert.ok(isCeSplitUrl("/api/split"));
  assert.ok(isCeSplitUrl("/embed/ce/api/split"));
  assert.ok(isCeSplitUrl("http://127.0.0.1:8815/embed/ce/api/split"));
  assert.ok(!isCeSplitUrl("/api/workspaces/split"));
  assert.ok(!isCeSplitUrl("/embed/ce/api/splitter"));
});

test("CE split body maps onto Switch Bay's workspace split", () => {
  assert.deepEqual(
    toSwitchbaySplitBody({ name: " team ", move: ["a", ""], copy: ["b"] }),
    { name: "team", move: ["a"], copy: ["b"] },
  );
  assert.deepEqual(
    toSwitchbaySplitBody({ target: "/home/ben/Workspaces/side-project/", move: ["x"] }),
    { name: "side-project", move: ["x"], copy: [] },
  );
  assert.deepEqual(toSwitchbaySplitBody(null), { name: "", move: [], copy: [] });
});
