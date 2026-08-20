# Enterprise packaging

This branch (`enterprise`) is Switch Bay with a machine-level **admin
policy**. The daemon **never writes** the policy file. An MDM / company
portal drops it; the user cannot turn providers back on from Settings.

Default on this branch, even with no file: **GitHub Copilot + local
models** (llama.cpp, MLX, Ollama). Hosted API keys and other coding
CLIs are hidden. Runtime hooks that EDR products flag stay off.

## Admin policy file

Search order (first existing file wins):

1. `$SWITCHBAY_ADMIN_POLICY` (absolute path)
2. `/Library/Application Support/SwitchBay/admin.json` (macOS MDM)
3. `/etc/switchbay/admin.json`
4. `<checkout>/admin.json` (optional drop-in; gitignored)

A template lives at [`config/admin.enterprise.json`](../config/admin.enterprise.json).
Copy it to one of the paths above. Own it as root, mode `0644`.

```json
{
  "profile": "enterprise",
  "providers": {
    "github_copilot": true,
    "llamacpp": true,
    "mlx": true,
    "ollama": true,
    "anthropic": false
  },
  "features": {
    "in_app_update": false,
    "ce_auto_setup": false,
    "hf_model_download": false
  }
}
```

- **`providers`** — per gateway id, on/off. Missing keys inherit the
  profile default (enterprise = Copilot + local only; `open` = all on).
- **`features`** — see table below. Missing keys inherit the profile.
- **`SWITCHBAY_PROFILE=open`** restores mainline behaviour without a file.

Provider ids: `github_copilot`, `llamacpp`, `mlx`, `ollama`,
`claude-code`, `grok-build`, `muse-code`, `openai-codex`, `anthropic`,
`xai`, `meta`, `openai`, `gemini`.

| Feature | Enterprise default | Why |
|---|---|---|
| `in_app_update` | off | Settings → Update runs `git pull` / `npx skills` as the user |
| `install_skills_npx` | off | `npx skills add -g` at service install |
| `ce_auto_setup` | off | CE `scripts/setup.sh` + `uv venv` per workspace |
| `uv_python_install` | off | `uv python install 3.13` (downloads a toolchain) |
| `scan_other_app_caches` | off | Walks `~/Library/Containers/*/…/huggingface` (TCC + EDR) |
| `hf_model_download` | off | Hugging Face GGUF/MLX fetch from Settings |
| `comms_streams` | off | IMAP / Gmail / Slack / … as ingest sources |
| `github_share` | off | `gh` publish of a workspace |
| `media_generation` | off | External image/video APIs |
| `user_mcp_servers` | on | Local MCP add is useful and stays on-box |
| `watch_folders` | on | Local directory poll |

## SentinelOne / EDR

In testing, SentinelOne flagged **persistent `uv` and `pnpm` jobs** and
**`setup.sh`**. Those are real: a consumer install runs them at first
launch and again when a workspace has no CE `.venv`.

**Design around it: do not run package managers at daemon start.**

This branch:

- Does **not** call `uv python install`, `uv venv`, `npx skills add`, or
  CE `setup.sh` unless the matching feature is explicitly enabled.
- The launchd/systemd unit already invokes
  `<repo>/.venv/bin/python -m switchbay serve` — **not** `uv run`.
- Settings → Update is hidden and the endpoint returns 403.

**What the company portal package must contain** (built on a blessed
builder, not on the employee Mac):

1. The Switch Bay tree with `.venv/` already `uv sync`'d (Python 3.13).
2. `frontend/dist/` already built (`pnpm --dir frontend run build` on
   the builder).
3. The curiosity-engine skill already on disk
   (`…/skills/curiosity-engine/scripts/setup.sh` present) — copy from
   the builder, do not `npx skills add` on the endpoint.
4. Optional: a **workspace template** whose `.venv` is pre-created so
   first open never runs `setup.sh`. With `ce_auto_setup: false`, a
   wiki without that venv still opens; the graph is nodes-only until
   IT provisions kuzu.
5. `admin.json` at the MDM path.

The employee machine then starts Python. No `uv`, no `pnpm`, no
`setup.sh`, no `curl | sh`.

## Other portal-review issues (and how this branch treats them)

| Issue | Risk | This branch |
|---|---|---|
| Always-on launchd agent (`KeepAlive`) | Persistence | Keep — required for the PWA. Document it as a per-user agent, not a privileged daemon. Program is `.venv/bin/python`. |
| Unsigned `python3.13` + Keychain / TCC “other apps” | Prompt fatigue, EDR | `scan_other_app_caches: false` skips Containers. Keys still use the OS keychain; Copilot uses device-flow, not a long-lived API key. |
| Hugging Face downloads | Egress, large writes | `hf_model_download: false`. IT can drop GGUF/MLX into the HF cache; the picker only lists what’s already on disk. |
| In-app git pull of Switch Bay + skills | Supply-chain, unexpected network | `in_app_update: false`. Updates go through the portal package. |
| Hosted LLM API keys (Anthropic, OpenAI, xAI, Gemini, Meta) | Data leaving the tenant | Hidden. Copilot stays inside the existing GitHub Enterprise / EMU subscription. |
| Coding CLIs (Claude Code, Grok, Codex, Muse) | Extra binaries, shell | Hidden. Copilot is HTTP; local models are HTTP to `localhost`. |
| Comms streams (mail, Slack, …) | OAuth, mailbox read | Off. |
| GitHub share (`gh repo create`) | Unapproved egress | Off. |
| FSL-1.1 license | Legal review | Internal use is in-scope. A Competing Use (reselling Switch Bay as a product) is not. Point counsel at `LICENSE`. |
| PWA vs signed `.app` | Portal wants a signed pkg | Out of scope here. Wrap `http://127.0.0.1:8765` in a signed helper or ship a pkg that registers the LaunchAgent + a bookmark. |
| Agent bash / MCP | Local code execution | Unchanged: permission cards + toolscope. User MCP stays available. Tighten later if required. |
| Localhost-only bind | Good | Unchanged (`127.0.0.1`). |

## Suggested portal install (macOS)

On the **builder**:

```sh
git clone --branch enterprise <url> /opt/switchbay
cd /opt/switchbay
uv python install 3.13
uv sync
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend run build
# vendor CE skill into the image, e.g. /opt/switchbay/vendor/curiosity-engine
```

On the **endpoint** (pkg postinstall, as the logged-in user):

```sh
# 1. Copy /opt/switchbay into place (or mount it).
# 2. Drop admin.json (root-owned):
sudo mkdir -p "/Library/Application Support/SwitchBay"
sudo cp admin.enterprise.json "/Library/Application Support/SwitchBay/admin.json"
# 3. Register the user agent WITHOUT running uv/pnpm/npx:
SWITCHBAY_PROFILE=enterprise \
  PYTHONPATH=/opt/switchbay/src \
  /opt/switchbay/.venv/bin/python -m switchbay service install
```

Point `$SWITCHBAY_CE_ROOT` at the vendored skill so the daemon never
calls `npx`.

Open `http://127.0.0.1:8765` and install the PWA. Copilot sign-in is
Settings → GitHub Copilot (device flow / Enterprise SSO).
