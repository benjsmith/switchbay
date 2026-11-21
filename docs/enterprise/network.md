# Network

[Enterprise security](index.md)

Switch Bay listens on the loopback interface and calls out only for
the features that are turned on. This page lists the listeners, the
loopback services, and the outbound calls.

## Listeners

| Port | Bind | Process | Who connects |
|---|---|---|---|
| `8765` (or `network.bind_port`) | `127.0.0.1`. Enterprise refuses any other address. | Switch Bay daemon | The browser app, `curl`, and local agent callbacks |
| `8878`–`8887` | `127.0.0.1` | Managed llama.cpp or MLX, one port per loaded model | The daemon, on the same machine |
| `11434` | Ollama's own bind, which Switch Bay treats as `127.0.0.1:11434` | Ollama, if the person installed it | The daemon, when the Ollama provider is on |
| `8766` | `127.0.0.1` | curiosity-engine viewer, started by the daemon | The daemon's proxy only |
| `8767` | `127.0.0.1` | okstratr, started by the daemon | The daemon's proxy only |

The daemon does not listen on a LAN address. There is no inbound
connection from another machine in a default or enterprise install.
Enterprise startup exits if `network.bind_host` is not `127.0.0.1`
or `::1`.

`SWITCHBAY_CE_UPSTREAM` and `SWITCHBAY_OKSTRATR_UPSTREAM` can retarget
the two proxies. A non-loopback URL is rejected.

Vite (`localhost:5173`) exists only in a development checkout. It
proxies `/api`, `/ws`, and `/embed` to `8765`. A company package
serves the built app from the daemon and does not run Vite.

## What the browser talks to

The app uses `http://127.0.0.1:8765` for HTTP and `ws://127.0.0.1:8765/ws`
for the session. Graph and Agents panels are loaded from the same
origin under `/embed/ce/` and `/embed/okstratr/`. The daemon proxies
those prefixes to `8766` and `8767` and adds `X-CE-Host: switchbay` or
`X-Okstratr-Host: switchbay`. The browser does not open `8766` or
`8767` itself.

Every request is subject to the Origin and Host checks in
[Posture](posture.md#the-daemons-own-boundary).

Routes an enterprise review will see, all on that one listener:

- `/api/*` — the app: settings, chat, files, proposals, streams,
  permissions, health.
- `/api/session/label`, `/api/exclusion-rules`,
  `/api/classification/queue`, `/api/classification/decide`,
  `/api/classification/mandatory`, `/api/public-write` and
  `/api/public-write/presidio`, `/confirm`, `/scope` — the controls
  in [Controls](controls.md).
- `/.well-known/agent-card.json`, `/.well-known/agent.json`, `POST /a2a`
  — local agent-to-agent calls between threads. Loopback only.
- `/embed/ce/*`, `/embed/okstratr/*` — the proxies above.

Switch Bay does not serve `ce-graph/1`. That API is what a *remote*
graph server speaks. This daemon is the client. See
[Mounted graphs](graphs.md).

## Outbound: what leaves the machine

Nothing leaves because the daemon is running. A call leaves when one
of the following happens.

**Models.** At startup the daemon wraps `aiohttp` and Python's
`urllib`, so in the enterprise profile those clients can open a URL
only when `egress_allowed` says yes: loopback, the Copilot hosts
below, hosts added by a feature flag, and `network.egress_allowlist`.
The open profile allows every host. `git`, `gh`, `npx`, and a
Playwright browser are separate processes; the wrap does not see
them. The feature flags are what turn those off.

Copilot, when that provider is on and the person has signed in:
device-code and token calls to the GitHub host (`github.com` or
`copilot.host`), then chat to `api.githubcopilot.com`. For
`github.com` the derived allowlist is `github.com`, `api.github.com`,
`api.githubcopilot.com`, and `copilot-proxy.githubusercontent.com`.
For any other host it is that host and `api.<host>`. Prompts and
tool results in that chat are sent to Copilot. Local llama.cpp, MLX,
and Ollama stay on loopback; the prompt does not leave for those
backends. Hosted APIs (Anthropic `api.anthropic.com`, OpenAI
`api.openai.com`, xAI `api.x.ai`, Gemini
`generativelanguage.googleapis.com`, Meta) are off in the enterprise
profile. Turning a provider on in `providers` lets that client run,
and the call still fails the egress wrap unless the host is on
`network.egress_allowlist`.

**Web search and fetch.** Off in the enterprise profile
(`web_egress` false) and off per workspace until the person enables
it. When both are on, each search or fetch asks once and the answer
is not remembered. The request goes to the search or fetch target
the tool uses. Codex's own web search stays off.

**Hugging Face.** Off in enterprise (`hf_model_download` false). On,
the egress allowlist adds `huggingface.co`, `hf.co`,
`cdn-lfs.huggingface.co`, and `cas-bridge.xethub.hf.co`.

**In-app update.** Off in enterprise. On, a git checkout may contact
`github.com`, `api.github.com`, `codeload.github.com`,
`raw.githubusercontent.com`, and `objects.githubusercontent.com`.

**GitHub publish.** Off in enterprise (`github_share` false). On,
`gh` pushes the workspace to GitHub. The preview lists files and
secret-shaped strings first, and publish refuses pages above
`public`. See [Controls](controls.md).

**Live graphs.** A saved live mount is queried at its `url` (4 second
timeout): OAuth discovery, then `/ce-graph/1/…`. Enterprise will not
save a remote mount with the current defaults, so this call does not
happen until a mount can be saved. See [Mounted graphs](graphs.md).

**Snapshots.** A snapshot URL that is a git remote runs `git clone`
or `git fetch` to that remote. A snapshot that is a local directory
does not use the network.

**External sources.** The source tool does not open a connection. It
uses an in-memory fake. See [External sources](sources.md).

**Comms (mail, Slack, Teams).** Off in enterprise
(`comms_streams` false). On, OAuth and polling go to the provider
the person connected. Bodies are not fetched until a thread is
approved, and some cases are refused before any body fetch. The
packaging guide has the comms rules: [Enterprise packaging](../enterprise.md#comms-classification-and-tenant-labels).

**Media generation.** Off in enterprise (`media_generation` false).
On, image and video calls go to the configured vendor.

**Browser tool.** Off in enterprise (`browser_use` false). On, a
local Playwright browser can reach the network when an agent drives
it.

**Skills install.** `install_skills_npx` defaults on, including in
enterprise. `npx` or `uvx skills add` then contacts the registry for
that skill, subject to `skills.allowlist`.

**Keychain.** API keys and graph tokens are stored in the OS
keychain (macOS Keychain, Windows Credential Manager, Linux Secret
Service). That is a local call. If no keychain is available, a graph
token falls back to a mode `0600` file under the state directory.
Provider API keys are not written to a file as a fallback; saving
them fails until a keychain works.

## Inbound from the machine itself

The daemon accepts loopback clients. That includes the browser, the
permission hook inside a coding CLI (a POST back to
`/api/permission/request` on the daemon port), and `ask_thread`,
which calls `/a2a` on loopback. User MCP servers configured as HTTP
are outbound from the coding CLI, not listeners of the daemon.
Switch Bay's own MCP server for those CLIs is stdio, not a port.
