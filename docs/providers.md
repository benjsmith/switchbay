# LLM providers — implementation status

How far each gateway is actually wired. The picker lists everyone below;
**listed ≠ first-class.** First-class here means: live-validated stream,
per-workspace Switch Bay MCP (`propose_*`, wiki tools, `create_report`),
and (for CLIs that support it) a rail approval card on novel tool calls.

HTTP providers never get a shell. They only see Switch Bay's tool
registry. Curation that must *run* CE scripts needs a CLI with
`shell` + `file_write` (see `llmgateway.can_execute`).

Last updated **2026-08-13**. Remaining Muse Code work waits on a live
`muse` install.

## Status key

| Mark | Meaning |
|---|---|
| **First-class** | Exercised against a live binary/API. MCP + stream + (CLI) rail cards or a documented equivalent. |
| **Usable** | Ships and will dispatch. One or more first-class surfaces missing or only docs-validated. |
| **Preview** | In the picker. Spawn/HTTP path written from public docs; not yet run live in this tree. |

## Subscription CLIs

| Provider | Status | MCP | Rail card | Notes |
|---|---|---|---|---|
| **Claude Code** (`claude-code`) | First-class | per-workspace `--mcp-config` | PreToolUse hook → rail | Scoped allowlist + CE toolscope. The reference CLI integration. |
| **Grok Build** (`grok-build`) | First-class | `grok mcp add` (project) | PreToolUse + `bypassPermissions` | Live `grok models` list (grok-4.6 as of CLI 1.0.3). Hook **fails open** — every error path emits deny. |
| **OpenAI Codex** (`openai-codex`) | Usable | inline `-c mcp_servers…` | no | Upstream has no PreToolUse. Workspace-write sandbox only. |
| **Muse Code** (`muse-code`) | Preview | **no** | **no** | See [Muse Code](#muse-code) below. |
| **GitHub Copilot** (`github_copilot`) | Usable | n/a (HTTP) | n/a | Device-flow + Enterprise SSO. OpenAI-compat tools. No shell. |

## Hosted APIs (BYOK)

| Provider | Status | Tools | Live model list | Notes |
|---|---|---|---|---|
| **Anthropic** (`anthropic`) | First-class | native | yes | Canonical tool dialect. |
| **xAI Grok** (`xai`) | First-class | OpenAI-compat | `GET /v1/models` | Sibling of Grok Build, not a substitute for it. |
| **OpenAI** (`openai`) | First-class | OpenAI-compat | yes | Sibling of Codex. |
| **Meta (Muse Spark)** (`meta`) | Usable | OpenAI-compat | `GET /v1/models` | Docs-validated (`https://api.meta.ai/v1`). Sibling of Muse Code. `reasoning_effort: none` is a 400 — Muse Spark always reasons. Contributor-tier ids may train on your data; default is `muse-spark-1.2`. Not live-keyed in this tree yet. |
| **Google Gemini** (`gemini`) | Usable | **no** | static + fetch | Chat/stream only; no tool loop. |

## Local

| Provider | Status | Notes |
|---|---|---|
| **llama.cpp** (`llamacpp`) | First-class | Managed `llama-server`, HF GGUF install. Fail-soft if nothing is installed. |
| **MLX** (`mlx`) | First-class | Apple silicon only; hidden elsewhere. |
| **Ollama** (`ollama`) | Usable | Uses whatever `ollama` is on PATH. |

## Muse Code

Ships so you can pick it once `muse` is on PATH. Written from
[Meta's public docs](https://dev.meta.ai/docs/muse-code) (2026-08), **not**
from a live binary in this checkout. Treat it as preview until the
items below land.

**What works on paper**

- Picker + Settings row (`muse-code`), default `muse-spark-1.2`
- Headless spawn: `muse exec --json --workspace … --trust-workspace --disable-approval`
- Reasoning rungs `minimal` … `xhigh` (never `none` / `ultra`)
- Session continue via `--session-id`
- `can_execute` is true — Meta's OS sandbox stays on (we never pass `--yolo`)
- Optional `META_API_KEY` / Settings Meta key forwarded if the env is empty

**What is not first-class yet** (needs a live `muse` install)

1. **JSONL stream contract** — `parse_exec_event` accepts sibling-CLI shapes. The real `muse exec --json` schema has not been captured.
2. **Rail approval cards** — spawn uses `--disable-approval`, so Meta's dangerous-set never stops for us either. Hook stdin/stdout dialect (`PreToolUse` / `PermissionRequest`) is unpublished in a form we can trust. Grok taught us empty hook output can mean *allow*.
3. **Per-workspace MCP** — Muse's documented MCP block is user-global (`~/.config/muse/settings.json`). Baking `CSWY_WORKSPACE` there would pin every project to one folder. No Switch Bay `propose_*` / wiki tools until there is a workspace-scoped injection.
4. **CE toolscope + hard denies** at the hook (home-wide `find` / `mdfind`).
5. **System/rules append** — no documented `--rules` flag; we prepend to the user prompt.
6. **`validate_key` / live model list** — binary presence only; `muse models` is best-effort.

Until then: use Claude Code or Grok Build when you need per-call rail cards or Switch Bay MCP tools. Prefer `muse-spark-1.2` over `muse-spark-1.2-contributor` unless you opt into Meta training on prompts.

## How to read the picker

Subscriptions first, then BYOK, then local (`llmgateway.PROVIDERS` order).
A provider with `has_key: false` is listed but cannot be set as default.
Paste-any-model-id is allowed (`force: true`); the live list is a
convenience, not a lock.
