import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import path from "node:path";

const require = createRequire(fileURLToPath(import.meta.url));
const playwrightRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const { chromium } = require(
  require.resolve("playwright", { paths: [playwrightRoot] }),
);

const [url, output] = process.argv.slice(2);
if (!url || !output) {
  throw new Error("usage: render-slideshow-pdf.mjs <url> <output.pdf>");
}

const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 1,
  });
  const response = await page.goto(url, { waitUntil: "networkidle", timeout: 60_000 });
  if (!response?.ok()) {
    throw new Error(`slideshow returned HTTP ${response?.status() ?? "unknown"}`);
  }
  await page.emulateMedia({ media: "print", colorScheme: "dark" });
  await page.evaluate(async () => {
    await document.fonts.ready;
    const images = [...document.images];
    await Promise.all(images.map((image) => {
      if (image.complete) return Promise.resolve();
      return new Promise((resolve) => {
        image.addEventListener("load", resolve, { once: true });
        image.addEventListener("error", resolve, { once: true });
      });
    }));
  });
  await page.pdf({
    path: output,
    width: "13.333in",
    height: "7.5in",
    preferCSSPageSize: true,
    printBackground: true,
    margin: { top: "0", right: "0", bottom: "0", left: "0" },
  });
} finally {
  await browser.close();
}
