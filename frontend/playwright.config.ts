import { defineConfig, devices } from "@playwright/test";

// Smoke-test config for the switchbay UI. Assumes the dev servers are
// already running (daemon on :8765, vite on :5173 — see README "Run
// (dev)"). We deliberately don't auto-start them here: the daemon needs
// a WORKSPACE and the node_modules symlink setup, which the developer
// already has live. Run with:  pnpm --dir frontend exec playwright test
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL || "http://localhost:5173",
    viewport: { width: 1400, height: 900 },
    trace: "off",
    // Headless Chromium has no GPU by default, which would send our
    // xterm WebGL renderer down its DOM fallback — and the whole point
    // of these shots is to verify the WebGL powerline rendering. Force
    // software WebGL (SwiftShader via ANGLE) so the screenshot matches
    // what the user sees in real Chrome.
    launchOptions: {
      args: [
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--ignore-gpu-blocklist",
        "--enable-unsafe-swiftshader",
      ],
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
