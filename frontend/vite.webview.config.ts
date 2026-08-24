import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

const dir = path.dirname(fileURLToPath(import.meta.url));

/** Standalone Graph/Atlas bundle for the VS Code webview. */
export default defineConfig({
  root: dir,
  base: "./",
  build: {
    outDir: path.resolve(dir, "../extensions/switchbay/media/graph"),
    emptyOutDir: true,
    rollupOptions: {
      input: path.resolve(dir, "webview-graph.html"),
    },
  },
});
