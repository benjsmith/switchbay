import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// Daemon defaults to 127.0.0.1:8765 (see src/switchbay/__main__.py).
const DAEMON = "http://127.0.0.1:8765";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    proxy: {
      "/api": DAEMON,
      "/ws": { target: DAEMON.replace("http", "ws"), ws: true },
      // CE's rendered body_html embeds <img src="figures/..."> with a
      // relative URL. In dev that resolves against localhost:5173 and
      // gets swallowed by Vite's SPA fallback; needs to reach the
      // daemon so handle_figure_file can serve from <ws>/figures/ or
      // <ws>/wiki/figures/ (PDF page rasters, sketch PNGs, etc.).
      "/figures": DAEMON,
    },
  },
});
