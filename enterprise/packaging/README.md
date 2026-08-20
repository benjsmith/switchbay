# Enterprise packaging kit

Packaging teams receive **platform payloads** (Win11 x64 and macOS
darwin arm64) from the GitHub release, plus this kit. Endpoints must
**not** run `uv`, `pnpm`, `npx`, or CE `setup.sh`.

## Profiles

| Profile | How | Behaviour |
|---|---|---|
| `open` | default (git checkout / consumer) | Today's product: every provider, Hugging Face downloads on |
| `enterprise` | `SWITCHBAY_PROFILE=enterprise` and/or admin.json `"profile": "enterprise"` | Copilot + local; downloads/hooks off unless an admin flag is true |

## Hugging Face downloads

Enterprise default is **off**. Admins may enable Settings → Find & install:

```json
"features": { "hf_model_download": true }
```

On-disk GGUF / MLX / Ollama models work either way.

## Payloads

Release assets (next release and later):

- `switchbay-enterprise-win11-x64.zip`
- `switchbay-enterprise-darwin-arm64.tar.gz`

Each contains:

- `python/cpython-*/` — relocatable CPython 3.13 + frozen `site-packages`
- `src/`
- `frontend/dist/`
- `config/admin.enterprise.json`
- `serve.cmd` / `serve.sh` — builder smoke only
- `SWITCHBAY_PROFILE` (contents: `enterprise`)

Stamp the service environment:

```
SWITCHBAY_PROFILE=enterprise
```

`service install` also reads a `SWITCHBAY_PROFILE` file at the tree root.

Windows overlay (MDM): `%ProgramData%\SwitchBay\admin.json`
macOS overlay: `/Library/Application Support/SwitchBay/admin.json`

Set `copilot.host` (github.com or your GHE URL) in that file at bake time.

Default workspace: `%USERPROFILE%\SwitchBay\workspace` (Windows) or
`~/SwitchBay/workspace` (macOS). IT may opt in to a cloud-synced home.

Windows launcher for employees: Edge only (`msedge --app=http://127.0.0.1:8765`).
macOS: Safari. Interactive PTY is Unix-only; Windows v1 has no rail shell.

Vendor the curiosity-engine skill on the **builder**, not the endpoint.

This release ships the frozen trees packaging teams wrap. WiX MSI,
notarized PKG, and the CPython host are later packaging PRs. Public
packaging notes: `docs/enterprise.md`.
