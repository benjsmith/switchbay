import { test, expect } from "@playwright/test";

test.use({
  baseURL: process.env.PLAYWRIGHT_BASE_URL || "http://localhost:5173",
});

const NOW = Date.now() / 1000;

const FAKE_RUNS = {
  runs: [
    {
      run_id: "run-space",
      provider: "openai",
      model: "gpt-5.4",
      input_excerpt: "[auto] research T",
      started_at: NOW - 12,
      last_chunk_at: NOW,
      tool_count: 2,
      status: "running",
      activity: "verify ×1",
      step: "verify ×1",
      workspace_name: "ws",
      orchestration_id: "run-space",
      orchestration_strategy: "investigate_verify_synthesize",
      decision_reason: "research-shaped request; verify",
      fanout_n: 2,
      workers_total: 4,
      workers_running: 1,
      preference: 0.7,
      tokens: 1800,
      verification_conflicts: 0,
      blackboard_n: 3,
      candidate_findings_n: 2,
      unique_sources: 2,
      blackboard_rows: [
        {
          id: "f-1", node_id: "inv-0", kind: "finding", verdict: "candidate",
          claim: "T is supported by the 2024 review", sources: 1, ts: NOW - 3,
        },
        {
          id: "f-2", node_id: "inv-1", kind: "finding", verdict: "supported",
          claim: "Neighbours of T agree on the mechanism", sources: 2, ts: NOW - 2,
        },
        {
          id: "ce-w0-dispatch", node_id: "ce-w0", kind: "dispatch", verdict: "",
          claim: "worker dispatched in-session by the CE orchestrator",
          sources: 0, ts: NOW - 1,
        },
      ],
      objective: "Research conflicting wiki evidence on T.",
      plan_nodes: [
        {
          node_id: "inv-0", kind: "investigate", role: "investigator",
          dependencies: [], objective: "wiki-search slice", status: "done",
          method_hint: "wiki-search: start with search_wiki",
        },
        {
          node_id: "inv-1", kind: "investigate", role: "investigator",
          dependencies: [], objective: "graph-neighborhood slice", status: "done",
          method_hint: "graph-neighborhood: walk wiki_neighbors",
        },
        {
          node_id: "verify", kind: "verify", role: "verifier",
          dependencies: ["inv-0", "inv-1"], objective: "Verify findings",
          status: "running",
        },
        {
          node_id: "synth", kind: "synthesize", role: "synthesizer",
          dependencies: ["verify"], objective: "Research T", status: "pending",
        },
      ],
      orchestration_messages: [
        { ts: NOW - 8, from: "chief", to: "inv-0", kind: "spawn", text: "investigate: wiki-search slice" },
        { ts: NOW - 7, from: "chief", to: "inv-1", kind: "spawn", text: "investigate: graph slice" },
        { ts: NOW - 3, from: "inv-0", to: "chief", kind: "findings", text: "1 finding(s) · T is supported" },
        { ts: NOW - 2, from: "inv-0", to: "verify", kind: "handoff", text: "verify: Verify findings" },
        { ts: NOW - 2, from: "inv-1", to: "verify", kind: "handoff", text: "verify: Verify findings" },
      ],
    },
    {
      run_id: "run-space-inv-0",
      parent_run_id: "run-space",
      node_id: "inv-0",
      node_kind: "investigate",
      provider: "openai",
      model: "gpt-5.4",
      input_excerpt: "wiki-search slice",
      started_at: NOW - 11,
      last_chunk_at: NOW - 4,
      tool_count: 78,
      status: "done",
      activity: "⚙ Read(path=wiki/index.md)",
      current_tool: "Read",
      worker_index: 0,
    },
    {
      run_id: "run-space-inv-1",
      parent_run_id: "run-space",
      node_id: "inv-1",
      node_kind: "investigate",
      provider: "github_copilot",
      model: "claude-sonnet-4.6",
      input_excerpt: "graph slice",
      started_at: NOW - 11,
      last_chunk_at: NOW - 3,
      tool_count: 1,
      status: "done",
      activity: "neighbors of T",
      worker_index: 1,
    },
    {
      run_id: "run-space-verify",
      parent_run_id: "run-space",
      node_id: "verify",
      node_kind: "verify",
      provider: "openai",
      model: "gpt-5.5",
      input_excerpt: "Verify findings",
      started_at: NOW - 2,
      last_chunk_at: NOW,
      tool_count: 0,
      status: "running",
      activity: "classifying claims",
    },
    {
      run_id: "run-other-ws",
      provider: "openai",
      model: "gpt-5.4",
      input_excerpt: "foreign desk",
      started_at: NOW - 5,
      last_chunk_at: NOW,
      tool_count: 0,
      status: "running",
      workspace: "/tmp/other-wiki",
      workspace_name: "other-wiki",
    },
  ],
};

test("agent space renders chief, pulses board, and drill-in", async ({ page }) => {
  await page.route("**/api/runs/active", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(FAKE_RUNS),
    });
  });
  await page.route("**/api/orchestration/org**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ org: null }),
    });
  });
  await page.route("**/api/orchestration/interrupted", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ runs: [] }),
    });
  });
  await page.route("**/api/tools", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ tools: [] }),
    });
  });
  await page.route("**/api/agent_rules", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ rules: [] }),
    });
  });
  await page.route("**/api/command_palettes", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        rung: { id: "normal", label: "normal", prompt_budget: 8000 },
        commands: [],
        catalog: [],
      }),
    });
  });
  await page.route("**/api/llm/providers", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        providers: [],
        keychain_available: false,
        keychain_backend: "none",
        default_provider: "",
      }),
    });
  });
  await page.route("**/api/orchestration/models", async (route) => {
    if (route.request().method() === "POST") {
      const posted = route.request().postDataJSON() as {
        key?: string; allowed?: boolean; provider?: string;
      };
      const copilotOff = posted.provider === "github_copilot" && posted.allowed === false;
      const gptOff = posted.key === "github_copilot/gpt-5.4" && posted.allowed === false;
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({
          ok: true,
          denied: copilotOff
            ? ["github_copilot/gpt-5.4", "github_copilot/claude-sonnet-4.6"]
            : gptOff ? [posted.key] : [],
          models: [
            {
              key: "github_copilot/gpt-5.4",
              provider: "github_copilot",
              provider_label: "GitHub Copilot",
              model: "gpt-5.4",
              category: "subscription",
              local: false,
              allowed: !(copilotOff || gptOff),
              strength: 0.76,
            },
            {
              key: "github_copilot/claude-sonnet-4.6",
              provider: "github_copilot",
              provider_label: "GitHub Copilot",
              model: "claude-sonnet-4.6",
              category: "subscription",
              local: false,
              allowed: !copilotOff,
              strength: 0.66,
            },
            {
              key: "mlx/qwen2.5-7b-instruct",
              provider: "mlx",
              provider_label: "MLX (Apple silicon)",
              model: "qwen2.5-7b-instruct",
              category: "local",
              local: true,
              allowed: true,
              strength: 0.26,
            },
          ],
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({
        denied: [],
        models: [
          {
            key: "github_copilot/gpt-5.4",
            provider: "github_copilot",
            provider_label: "GitHub Copilot",
            model: "gpt-5.4",
            category: "subscription",
            local: false,
            allowed: true,
            strength: 0.76,
          },
          {
            key: "github_copilot/claude-sonnet-4.6",
            provider: "github_copilot",
            provider_label: "GitHub Copilot",
            model: "claude-sonnet-4.6",
            category: "subscription",
            local: false,
            allowed: true,
            strength: 0.66,
          },
          {
            key: "mlx/qwen2.5-7b-instruct",
            provider: "mlx",
            provider_label: "MLX (Apple silicon)",
            model: "qwen2.5-7b-instruct",
            category: "local",
            local: true,
            allowed: true,
            strength: 0.26,
          },
        ],
      }),
    });
  });
  await page.route("**/api/rail/events**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify({ events: [] }),
    });
  });

  await page.goto("/");
  await page.locator(".sy-tabstrip, .sy-zen").first().waitFor({ timeout: 20_000 });
  await page.getByRole("tab", { name: "Agents" }).click({ timeout: 15_000 });

  const space = page.locator(".sy-agent-space");
  await expect(space).toBeVisible({ timeout: 10_000 });
  await expect(space.getByRole("heading", { name: "Agent space" })).toBeVisible();
  await expect(space.locator("canvas.sy-agent-space-canvas")).toBeVisible();
  await expect(space.getByRole("heading", { name: "Chief of staff" })).toBeVisible();
  await expect(space.getByText("2 investigators")).toBeVisible();
  await expect(space.getByRole("heading", { name: "Message board" })).toBeVisible();
  await expect(space.getByText("blackboard").first()).toBeVisible();
  await expect(space.getByText("inv-0").first()).toBeVisible();
  await expect(space.getByText("78 tools").first()).toBeVisible();
  await expect(space.getByText("1 running").first()).toBeVisible();
  await expect(space.locator(".sy-agent-space-msg-route").filter({ hasText: "chief" }).first()).toBeVisible();
  await expect(space.getByText("1 finding(s)", { exact: false })).toBeVisible();

  await space.locator(".sy-agent-space-roster-btn").filter({ hasText: "verify" }).click();
  await expect(space.getByRole("heading", { name: "verifier" })).toBeVisible();
  await expect(space.locator(".sy-agent-space-activity")).toContainText("classifying");
  await space.getByRole("button", { name: /chief of staff/ }).click();
  await expect(space.getByRole("heading", { name: "Chief of staff" })).toBeVisible();

  await space.locator(".sy-agent-space-roster-btn").filter({ hasText: "blackboard" }).click();
  await expect(space.getByRole("heading", { name: "Blackboard" })).toBeVisible();
  // The board's live contents, newest first, in their own scroll box —
  // counters alone read as broken when they sit at zero.
  const rows = space.locator(".sy-agent-space-bb-rows > li");
  await expect(rows).toHaveCount(3);
  await expect(rows.first()).toContainText("dispatched in-session");
  await expect(rows.last()).toContainText("T is supported");
  await expect(space.locator(".sy-agent-space-bb-rows")).toHaveCSS(
    "overflow-y", "auto",
  );

  await expect(page.getByRole("heading", { name: "Recently finished" })).toHaveCount(0);
  const models = page.locator(".sy-orch-models");
  await expect(models.getByRole("heading", { name: "Chief of staff models" })).toBeVisible();
  await expect(models.getByText("GitHub Copilot")).toBeVisible();
  const gpt = models.getByRole("checkbox", { name: "gpt-5.4" });
  await expect(gpt).toBeChecked();
  await gpt.uncheck();
  await expect(gpt).not.toBeChecked();
  await models.getByRole("button", { name: "Deselect all" }).first().click();
  await expect(gpt).not.toBeChecked();
  await expect(models.getByRole("checkbox", { name: "claude-sonnet-4.6" })).not.toBeChecked();
  await expect(models.getByRole("checkbox", { name: "qwen2.5-7b-instruct" })).toBeChecked();
  await page.getByRole("button", { name: /Workspaces/ }).click();
  await expect(page.getByRole("button", { name: /other-wiki/ })).toBeVisible();
  await expect(page.getByText("foreign desk")).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "Schedules" })).toBeVisible();
  await expect(page.getByRole("button", { name: "+ schedule" })).toBeVisible();

  const runBoxes = await page.locator(".sy-agents-run").evaluateAll((els) =>
    els.map((el) => {
      const r = (el as HTMLElement).getBoundingClientRect();
      return { y: r.y, bottom: r.bottom, height: r.height };
    }),
  );
  for (let i = 1; i < runBoxes.length; i++) {
    expect(runBoxes[i]!.y + 0.5).toBeGreaterThanOrEqual(runBoxes[i - 1]!.bottom);
  }
});
