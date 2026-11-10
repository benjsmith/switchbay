import assert from "node:assert/strict";
import { test } from "node:test";
import {
  CHAT_UPLOAD_URL,
  applyImagePaste,
  attachmentsPending,
  clipboardImages,
  messageForSubmit,
  planComposerSubmit,
  uploadChatAttachment,
  uploadName,
  type ClipboardLike,
  type ComposerSelection,
} from "./imagePaste.ts";

function png(name: string, bytes = "png", lastModified = 1, type = "image/png"): File {
  return new File([bytes], name, { type, lastModified });
}

function clip(opts: {
  text?: string;
  files?: File[];
  items?: { kind: string; type: string; file: File | null }[];
  textThrows?: boolean;
}): ClipboardLike {
  return {
    files: opts.files,
    items: (opts.items ?? []).map((item) => ({
      kind: item.kind,
      type: item.type,
      getAsFile: () => item.file,
    })),
    getData: (format: string) => {
      if (opts.textThrows) throw new Error("denied");
      return format === "text/plain" ? (opts.text ?? "") : "";
    },
  };
}

const draft = (value: string, start: number, end = start): ComposerSelection => ({
  value,
  selectionStart: start,
  selectionEnd: end,
});

test("plain text paste is not intercepted", () => {
  const composer = draft("keep this", 4);
  const result = applyImagePaste(clip({ text: "HELLO" }), composer);
  assert.deepEqual(result, { kind: "text" });
  assert.equal(composer.value, "keep this");
  assert.equal(composer.selectionStart, 4);
});

test("rich text paste is not intercepted", () => {
  const result = applyImagePaste(
    clip({
      text: "hello",
      items: [
        { kind: "string", type: "text/plain", file: null },
        { kind: "string", type: "text/html", file: null },
      ],
    }),
    draft("stay", 4),
  );
  assert.deepEqual(result, { kind: "text" });
});

test("a non-image file paste is not intercepted", () => {
  const pdf = new File(["%PDF"], "notes.pdf", { type: "application/pdf" });
  const result = applyImagePaste(
    clip({
      text: "notes",
      files: [pdf],
      items: [{ kind: "file", type: "application/pdf", file: pdf }],
    }),
    draft("keep", 0),
  );
  assert.deepEqual(result, { kind: "text" });
});

test("an empty clipboard is not intercepted", () => {
  assert.deepEqual(applyImagePaste(null, draft("keep", 0)), { kind: "text" });
  assert.deepEqual(applyImagePaste(clip({}), draft("keep", 0)), { kind: "text" });
});

test("a screenshot paste attaches the image and leaves the draft alone", () => {
  const shot = png("image.png", "PNGDATA", 50);
  const result = applyImagePaste(
    clip({
      text: "",
      files: [shot],
      items: [{ kind: "file", type: "image/png", file: shot }],
    }),
    draft("draft", 5),
  );
  assert.equal(result.kind, "images");
  if (result.kind !== "images") return;
  assert.deepEqual(result.files, [shot]);
  assert.equal(result.value, "draft");
  assert.equal(result.cursor, 5);
});

test("one paste attaches every image", () => {
  const a = png("a.png", "a", 1);
  const b = png("b.jpg", "bb", 2, "image/jpeg");
  const result = applyImagePaste(clip({ files: [a, b] }), draft("", 0));
  assert.equal(result.kind, "images");
  if (result.kind !== "images") return;
  assert.deepEqual(result.files, [a, b]);
});

test("an image listed on both clipboard lists is attached once", () => {
  const shot = png("image.png", "PNG", 9);
  const copy = png("image.png", "PNG", 9);
  const files = clipboardImages(clip({
    files: [shot],
    items: [{ kind: "file", type: "image/png", file: copy }],
  }));
  assert.equal(files.length, 1);
});

test("two images that share a name are both kept", () => {
  const one = png("image.png", "AAA", 5);
  const two = png("image.png", "BBB", 5);
  const oneCopy = png("image.png", "AAA", 5);
  const twoCopy = png("image.png", "BBB", 5);
  const files = clipboardImages(clip({
    files: [oneCopy, twoCopy],
    items: [
      { kind: "file", type: "image/png", file: one },
      { kind: "file", type: "image/png", file: two },
    ],
  }));
  assert.equal(files.length, 2);
  assert.deepEqual(files.map((file) => file.size), [one.size, two.size]);
});

test("accompanying text is inserted at the caret and replaces a selection", () => {
  const shot = png("shot.png");
  const inserted = applyImagePaste(
    clip({ text: "!", files: [shot] }),
    draft("hello world", 5),
  );
  assert.equal(inserted.kind, "images");
  if (inserted.kind === "images") {
    assert.equal(inserted.value, "hello! world");
    assert.equal(inserted.cursor, 6);
    assert.deepEqual(inserted.files, [shot]);
  }
  const replaced = applyImagePaste(
    clip({ text: "look", files: [shot] }),
    draft("hello world", 6, 11),
  );
  assert.equal(replaced.kind, "images");
  if (replaced.kind === "images") {
    assert.equal(replaced.value, "hello look");
    assert.equal(replaced.cursor, 10);
  }
});

test("whitespace-only clipboard text does not change the draft", () => {
  const shot = png("shot.png");
  const result = applyImagePaste(
    clip({ text: " \n\t ", files: [shot] }),
    draft("draft", 5),
  );
  assert.equal(result.kind, "images");
  if (result.kind !== "images") return;
  assert.equal(result.value, "draft");
  assert.equal(result.cursor, 5);
});

test("a clipboard that refuses text still attaches the image", () => {
  const shot = png("image.png");
  const result = applyImagePaste(
    clip({ files: [shot], textThrows: true }),
    draft("draft", 0),
  );
  assert.equal(result.kind, "images");
  if (result.kind !== "images") return;
  assert.deepEqual(result.files, [shot]);
  assert.equal(result.value, "draft");
});

test("an item MIME type fills in an unnamed file", () => {
  const raw = new File(["jj"], "", { type: "" });
  const files = clipboardImages({
    items: [{ kind: "file", type: "image/jpeg", getAsFile: () => raw }],
  });
  assert.equal(files.length, 1);
  assert.equal(files[0]?.type, "image/jpeg");
  assert.equal(uploadName(files[0]!), "pasted-image.jpg");
});

test("upload names keep a real filename and name a blank one", () => {
  assert.equal(uploadName(png("shot.png")), "shot.png");
  assert.equal(uploadName(new File(["x"], "", { type: "image/jpeg" })), "pasted-image.jpg");
  assert.equal(uploadName(new File(["x"], "blob", { type: "image/png" })), "pasted-image.png");
  assert.equal(uploadName(new File(["x"], "   ", { type: "image/gif" })), "pasted-image.gif");
  assert.equal(uploadName(new File(["x"], "", { type: "" })), "pasted-image.png");
});

test("the outgoing message uses [attached: path] lines", () => {
  const one = ".workbench/uploads/aaa/one.png";
  const two = ".workbench/uploads/bbb/two.png";
  assert.equal(
    messageForSubmit("what is this?", [one, two], false),
    `[attached: ${one}]\n[attached: ${two}]\nwhat is this?`,
  );
  assert.equal(messageForSubmit("  ", [one], false), `[attached: ${one}]`);
  assert.equal(
    messageForSubmit("hi", [one, one, "  "], false),
    `[attached: ${one}]\nhi`,
  );
  assert.equal(messageForSubmit("  hello  ", [], false), "hello");
  assert.equal(messageForSubmit("   ", [], false), null);
});

test("removing a pasted image drops it from the message", () => {
  const one = ".workbench/uploads/aaa/one.png";
  const two = ".workbench/uploads/bbb/two.png";
  const attachments = [
    { id: "1", status: "ready", path: one },
    { id: "2", status: "ready", path: two },
  ];
  const kept = attachments.filter((item) => item.id !== "1");
  const plan = planComposerSubmit("see", kept, false);
  assert.deepEqual(plan, {
    blocked: false,
    message: `[attached: ${two}]\nsee`,
  });
});

test("text with no image still sends as a shell command; an image sends as chat", () => {
  assert.equal(messageForSubmit("ls -la", [], true), "!ls -la");
  assert.equal(messageForSubmit("ls -la", [], false), "ls -la");
  const path = ".workbench/uploads/aaa/shot.png";
  assert.equal(
    messageForSubmit("ls -la", [path], true),
    `[attached: ${path}]\nls -la`,
  );
});

test("an in-flight upload blocks send and a failed one is left out", () => {
  assert.deepEqual(
    planComposerSubmit("hi", [{ status: "uploading", path: null }], false),
    { blocked: true },
  );
  const ready = ".workbench/uploads/aaa/shot.png";
  assert.deepEqual(
    planComposerSubmit("hi", [
      { status: "uploading", path: null },
      { status: "ready", path: ready },
    ], false),
    { blocked: true },
  );
  assert.deepEqual(
    planComposerSubmit("hi", [{ status: "error", path: null }], false),
    { blocked: false, message: "hi" },
  );
  assert.equal(attachmentsPending([{ status: "ready" }]), true);
  assert.equal(attachmentsPending([{ status: "uploading" }]), true);
  assert.equal(attachmentsPending([{ status: "error" }]), false);
  assert.equal(attachmentsPending([]), false);
});

test("upload posts the file to /api/chat/upload", async () => {
  const file = png("shot.png", "xyz");
  const seen = { url: "", method: "", name: "", size: -1, called: false };
  const fetchImpl: typeof fetch = async (input, init) => {
    const form = init?.body as FormData;
    const uploaded = form.get("file") as File;
    seen.url = String(input);
    seen.method = init?.method ?? "";
    seen.name = uploaded.name;
    seen.size = uploaded.size;
    seen.called = true;
    return new Response(
      JSON.stringify({
        ok: true,
        path: ".workbench/uploads/abc/shot.png",
        size: 3,
        filename: "shot.png",
      }),
      { status: 200, headers: { "Content-Type": "application/json" } },
    );
  };
  const result = await uploadChatAttachment(file, fetchImpl);
  assert.equal(seen.called, true);
  assert.equal(seen.url, CHAT_UPLOAD_URL);
  assert.equal(seen.method, "POST");
  assert.equal(seen.name, "shot.png");
  assert.equal(seen.size, 3);
  assert.deepEqual(result, {
    path: ".workbench/uploads/abc/shot.png",
    size: 3,
    filename: "shot.png",
  });
});

test("upload failure surfaces the server error", async () => {
  const fetchImpl: typeof fetch = async () => new Response(
    JSON.stringify({ error: "file too large (>25 MB)" }),
    { status: 413, headers: { "Content-Type": "application/json" } },
  );
  await assert.rejects(
    () => uploadChatAttachment(png("big.png"), fetchImpl),
    /file too large \(>25 MB\)/,
  );
});

test("upload failure without a message reports the status", async () => {
  const fetchImpl: typeof fetch = async () => new Response("nope", { status: 500 });
  await assert.rejects(
    () => uploadChatAttachment(png("x.png"), fetchImpl),
    /500/,
  );
});
