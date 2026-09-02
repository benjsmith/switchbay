import assert from "node:assert/strict";
import { test } from "node:test";
import {
  dirContainsHit,
  displayNameForWikiRoot,
  normalizeRel,
  relIsHit,
  withWikiPrefix,
} from "./searchHits";

test("normalizeRel strips dots and slashes", () => {
  assert.equal(normalizeRel("./wiki/x.md"), "wiki/x.md");
  assert.equal(normalizeRel("/vault/a.pdf"), "vault/a.pdf");
  assert.equal(normalizeRel("wiki\\x.md"), "wiki/x.md");
});

test("withWikiPrefix roots bare page paths", () => {
  assert.equal(withWikiPrefix("entities/resnet.md"), "wiki/entities/resnet.md");
  assert.equal(withWikiPrefix("wiki/entities/resnet.md"), "wiki/entities/resnet.md");
  assert.equal(withWikiPrefix("vault/raw.pdf"), "vault/raw.pdf");
});

test("relIsHit matches wiki-prefixed and bare paths", () => {
  const hits = ["wiki/entities/resnet.md"];
  assert.equal(relIsHit("entities/resnet.md", hits), true);
  assert.equal(relIsHit("wiki/entities/resnet.md", hits), true);
  assert.equal(relIsHit("./wiki/entities/resnet.md", hits), true);
  assert.equal(relIsHit("wiki/entities/other.md", hits), false);
});

test("dirContainsHit expands ancestors of a page hit", () => {
  const hits = ["wiki/entities/resnet.md"];
  assert.equal(dirContainsHit("wiki", hits), true);
  assert.equal(dirContainsHit("wiki/entities", hits), true);
  assert.equal(dirContainsHit("", hits), true);
  assert.equal(dirContainsHit("vault", hits), false);
});

test("displayNameForWikiRoot is the folder basename", () => {
  assert.equal(displayNameForWikiRoot("/Users/benj/Workspaces/curiosity-test"), "curiosity-test");
  assert.equal(displayNameForWikiRoot("/Users/benj/Workspaces/curiosity-test/"), "curiosity-test");
  assert.equal(displayNameForWikiRoot(undefined), undefined);
});
