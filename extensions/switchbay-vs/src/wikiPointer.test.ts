import assert from "node:assert/strict";
import { test } from "node:test";
import {
  candidateImagePaths,
  expandImageWikilinks,
  expandUserPath,
  extractMarkdownImages,
  looksLikeCeWorkspace,
  looksLikeVisionModel,
  parseCuriosityConfig,
  parseSbhArg,
} from "./wikiPointer";

test("parseCuriosityConfig reads CE pointer schema", () => {
  const p = parseCuriosityConfig(`
# comment
workspace = "~/Documents/curiosity-workspace"
project = "myapp"
project_kind = "code"

[ingest]
enabled = true
`);
  assert.ok(p);
  assert.equal(p!.workspace, "~/Documents/curiosity-workspace");
  assert.equal(p!.project, "myapp");
  assert.equal(p!.projectKind, "code");
});

test("parseCuriosityConfig ignores missing workspace", () => {
  assert.equal(parseCuriosityConfig("project = \"x\"\n"), null);
});

test("expandUserPath", () => {
  assert.equal(expandUserPath("~/wiki", "/Users/benj"), "/Users/benj/wiki");
  assert.equal(expandUserPath("/abs", "/Users/benj"), "/abs");
});

test("looksLikeCeWorkspace", () => {
  assert.equal(looksLikeCeWorkspace({
    hasWikiDir: true, hasCuratorConfig: false, hasWikiGit: false,
  }), true);
  assert.equal(looksLikeCeWorkspace({
    hasWikiDir: false, hasCuratorConfig: false, hasWikiGit: false,
  }), false);
});

test("extractMarkdownImages sees Obsidian and markdown figures", () => {
  const md = [
    "See ![[figures/_assets/plot.png|ROC]] and a page [[concepts/foo]].",
    "![alt](_assets/x.jpg)",
  ].join("\n");
  const imgs = extractMarkdownImages(md);
  assert.equal(imgs.length, 2);
  assert.equal(imgs[0]!.src, "figures/_assets/plot.png");
  assert.equal(imgs[1]!.src, "_assets/x.jpg");
});

test("expandImageWikilinks leaves non-image wikilinks", () => {
  const out = expandImageWikilinks("![[figures/_assets/a.png]] and [[note]]");
  assert.match(out, /!\[\]\(figures\/_assets\/a\.png\)/);
  assert.match(out, /\[\[note\]\]/);
});

test("looksLikeVisionModel", () => {
  assert.equal(looksLikeVisionModel("gpt-4o", "gpt-4o", "GPT-4o"), true);
  assert.equal(looksLikeVisionModel("claude-sonnet-4", "claude", "Sonnet"), true);
  assert.equal(looksLikeVisionModel("gpt-3.5-turbo", "gpt-3.5-turbo", "GPT 3.5"), false);
  assert.equal(looksLikeVisionModel("text-embedding-3-small", "", ""), false);
});

test("parseSbhArg", () => {
  assert.equal(parseSbhArg(""), "ask");
  assert.equal(parseSbhArg("on"), "on");
  assert.equal(parseSbhArg("OFF"), "off");
  assert.equal(parseSbhArg("maybe"), "ask");
});

test("candidateImagePaths prefers page dir then wiki figures", () => {
  const c = candidateImagePaths(
    "_assets/plot.png",
    "/ws/wiki/figures",
    "/ws",
  );
  assert.ok(c.includes("/ws/wiki/figures/_assets/plot.png"));
  assert.ok(c.includes("/ws/wiki/figures/_assets/plot.png") || c.includes("/ws/wiki/figures/_assets/plot.png"));
  assert.ok(c.some((p) => p.endsWith("wiki/figures/_assets/plot.png")));
});
