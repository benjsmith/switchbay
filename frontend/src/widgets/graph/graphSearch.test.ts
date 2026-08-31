import assert from "node:assert/strict";
import { test } from "node:test";
import {
  hitPagePaths,
  hitSourcePaths,
  matchGraphNodes,
  peekPersistedQuery,
  persistGraphQuery,
  wikiFilePath,
  type GraphSearchHit,
} from "./graphSearch.ts";
import type { GraphData } from "./types.ts";

const data: GraphData = {
  workspace: "/tmp/ws",
  generated_at: "",
  palette: {},
  nodes: [
    { id: "alpha", path: "concepts/alpha.md", type: "concept", title: "Alpha particle", degree: 2 },
    { id: "beta", path: "wiki/entities/beta.md", type: "entity", title: "Beta decay", degree: 1 },
    { id: "src-1", path: "sources/paper.md", type: "source", title: "Paper", degree: 0 },
  ],
  edges: [],
  pages: {
    alpha: {
      id: "alpha",
      title: "Alpha particle",
      type: "concept",
      path: "concepts/alpha.md",
      properties: {
        sources: [
          "vault/raw/helium.pdf",
          "20260417-101643-local-helium.md.extracted.md",
          "https://example.com/helium",
        ],
      },
      body_html: "",
    },
    beta: {
      id: "beta",
      title: "Beta decay",
      type: "entity",
      path: "wiki/entities/beta.md",
      properties: {},
      body_html: "",
    },
    "src-1": {
      id: "src-1",
      title: "Paper",
      type: "source",
      path: "sources/paper.md",
      properties: {},
      body_html: "",
    },
  },
};

test("wikiFilePath prefixes wiki/ unless already rooted", () => {
  assert.equal(wikiFilePath("concepts/a.md"), "wiki/concepts/a.md");
  assert.equal(wikiFilePath("wiki/entities/b.md"), "wiki/entities/b.md");
  assert.equal(wikiFilePath("vault/raw/x.pdf"), "vault/raw/x.pdf");
  assert.equal(wikiFilePath(""), "");
});

test("matchGraphNodes is substring over title/id/type", () => {
  assert.deepEqual(matchGraphNodes(data, "  ").map((h) => h.id), []);
  const alpha = matchGraphNodes(data, "alpha");
  assert.equal(alpha.length, 1);
  assert.equal(alpha[0]!.id, "alpha");
  assert.equal(alpha[0]!.path, "wiki/concepts/alpha.md");
  assert.ok(matchGraphNodes(data, "DECAY").some((h) => h.id === "beta"));
  assert.ok(matchGraphNodes(data, "entity").some((h) => h.id === "beta"));
});

test("hits split into matched pages and their vault provenance", () => {
  const hits: GraphSearchHit[] = matchGraphNodes(data, "alpha");
  assert.deepEqual(hitPagePaths(hits), ["wiki/concepts/alpha.md"]);

  const sources = hitSourcePaths(data, hits);
  assert.ok(sources.includes("vault/raw/helium.pdf"));
  // A bare `sources:` entry is an ingest filename in the vault, not a
  // wiki page — prefixing it with wiki/ pointed at a file that has
  // never existed, so source files never lit up in the browsers.
  assert.ok(sources.includes("vault/20260417-101643-local-helium.md.extracted.md"));
  assert.ok(!sources.some((p) => p.startsWith("http")));
  // The page itself is not repeated as its own provenance.
  assert.ok(!sources.includes("wiki/concepts/alpha.md"));
});

test("persisted query survives until cleared and ignores other workspaces", () => {
  persistGraphQuery("/tmp/ws", "attention");
  assert.equal(peekPersistedQuery("/tmp/ws"), "attention");
  assert.equal(peekPersistedQuery("/tmp/other"), "");
  persistGraphQuery("/tmp/ws", "");
  assert.equal(peekPersistedQuery("/tmp/ws"), "");
});
