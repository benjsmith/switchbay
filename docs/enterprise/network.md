# Network

## Listeners

| Port | Bind | Process |
|---|---|---|
| `8765`, or `network.bind_port` | `127.0.0.1`. Enterprise refuses anything else. | Switch Bay daemon |
| `8878`–`8887` | `127.0.0.1` | Managed llama.cpp or MLX, one port per model |
| `11434` | Whatever Ollama binds. Switch Bay calls `127.0.0.1:11434`. | Ollama, when that provider is on |
| `8766` | `127.0.0.1` | curiosity-engine viewer, started by the daemon |
| `8767` | `127.0.0.1` | okstratr, started by the daemon |

`SWITCHBAY_CE_UPSTREAM` and `SWITCHBAY_OKSTRATR_UPSTREAM` can move the two proxies. A non-loopback URL is rejected. There is no inbound listener on a LAN address.

The browser talks only to the daemon. `/embed/ce/*` and `/embed/okstratr/*` are proxied, with `X-CE-Host: switchbay` or `X-Okstratr-Host: switchbay`. `POST /a2a` and `/.well-known/agent-card.json` are the local agent-to-agent endpoint, same loopback checks. Switch Bay does not serve `ce-graph/1`. It is a client of that API.

PKCE listens on an ephemeral `127.0.0.1` port for one sign-in, then closes it.

## What leaves the machine

Nothing leaves because the daemon is running.

**Models.** Enterprise `aiohttp` and `urllib` calls are limited to loopback, the Copilot hosts, hosts added by a feature flag, and `network.egress_allowlist`. For `copilot.host` of `github.com` the derived hosts are `github.com`, `api.github.com`, `api.githubcopilot.com`, and `copilot-proxy.githubusercontent.com`. Another host adds that name and `api.<host>`. Copilot chat sends the prompt and tool results to `api.githubcopilot.com`. llama.cpp, MLX, and Ollama stay on loopback. Turning on Anthropic (`api.anthropic.com`), OpenAI (`api.openai.com`), xAI (`api.x.ai`), Gemini (`generativelanguage.googleapis.com`), or Meta still fails the egress wrap until that host is on `network.egress_allowlist`.

**Web search.** `web_egress` is off in enterprise, and off per workspace until the person enables it. Each search or fetch then asks once. The answer is not remembered. Codex's own web search stays off.

**Hugging Face.** Off unless `hf_model_download` is on, which adds `huggingface.co`, `hf.co`, `cdn-lfs.huggingface.co`, and `cas-bridge.xethub.hf.co`.

**In-app update.** Off unless `in_app_update` is on, which adds `github.com`, `api.github.com`, `codeload.github.com`, `raw.githubusercontent.com`, and `objects.githubusercontent.com`.

**GitHub publish.** Off unless `github_share` is on. `gh` then pushes. The preview lists files and secret-shaped strings. Publish refuses the export cap in [Controls](controls.md).

**Live graphs and snapshots.** A saved live mount is queried at its URL. A git snapshot URL runs `git clone` or `git fetch` in a subprocess, which the egress wrap does not see. Enterprise will not save the mount unless the allowlist and the egress list both allow it.

**Sources.** `call_source` POSTs to the configured URL through the wrapped HTTP client, so enterprise egress applies.

**PDF labeling.** `exports.purview.endpoint`, when set, is called once per slideshow PDF export (4 second timeout, no retry). Enterprise egress applies to that URL. The request body is the labelled PDF. If the host is not allowed, or the call fails, the export is refused and no file is written. With the endpoint empty, PDF export does not leave the machine.

**Comms, media, browser, skills.** Off in enterprise except `install_skills_npx`, which defaults on. `npx` / `uvx` are subprocesses. `skills.allowlist` restricts the ref. `comms_streams`, `media_generation`, and `browser_use` are the flags that turn the others on.

**Keychain.** Local. A missing keychain stores a graph token in a `0600` file. Provider API keys are not written to a file. Saving them fails until a keychain works.
