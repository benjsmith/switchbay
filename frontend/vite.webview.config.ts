import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const dir = path.dirname(fileURLToPath(import.meta.url));

/** VS Code graph webview: a thin host that loads Curiosity Engine's viewer. */
export default defineConfig({
  root: dir,
  base: "./",
  // PWA icons / service worker belong to the app, not the webview.
  publicDir: false,
  build: {
    outDir: path.resolve(dir, "../extensions/switchbay-vs/media/graph"),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(dir, "webview-graph.html"),
    },
  },
});
