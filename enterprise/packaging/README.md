# Enterprise packaging

Two jobs. Do not mix them.

| Who | What they get | What they run |
|---|---|---|
| **IT admin** (Intune / Jamf) | `dist/bake/` from packaging (Win32 scripts + layout, or a `.pkg`) | The **IT admin** section below |
| **Bake machine** | The unsigned zip/tar from the GitHub release | **One command**, then optionally sign, then hand the result to IT |

After bake, the company picks a trust model (both are supported):

| | Unsigned MDM (option 2) | Company-signed |
|---|---|---|
| What | Intune/Jamf installs to Program Files; EDR **path/hash allowlist** on that tree | Same install, plus Authenticode / Developer ID + notarize on the bake output |
| When | No code-signing identity, or internal tools that are never user-downloaded | Want VS Code-like Gatekeeper/SmartScreen, or SOC requires signed LOB |
| SentinelOne | Path allow `%ProgramFiles%\SwitchBay\**` (and the Mac install dir). Do **not** globally exclude `python.exe`. | After `switchbay.exe` is signed, use `sentinelone/SwitchBay-exclusions.json` (that exe, not `python.exe`). |

MDM install does not go through the browser quarantine path, so unsigned often never shows a Gatekeeper/SmartScreen dialog. Signing does not change policy, Copilot, or the Intune fields.

Endpoints never run `uv`, `pnpm`, `npx`, or curiosity-engine `setup.sh`.

SKUs: **Win11 x64** and **macOS darwin arm64** only.

---

## IT admin (after bake)

### Windows — Intune

Same motion as a LOB Win32 app.

1. Receive `dist/bake/` from packaging. Signing is optional (table above).
2. Wrap it with the Microsoft Win32 Content Prep Tool (`IntuneWinAppUtil.exe`) if you need `.intunewin`.
3. Intune → **Apps → Windows → Add → Windows app (Win32)**.

| Field | Value |
|---|---|
| Install | `powershell.exe -ExecutionPolicy Bypass -File install.ps1` |
| Uninstall | `powershell.exe -ExecutionPolicy Bypass -File uninstall.ps1` |
| Detection | `detection.ps1` |
| Install behavior | **System** |
| Assignment | User group |
| Restart | No |

4. Optional: deploy `%ProgramData%\SwitchBay\admin.json` as a separate Device configuration / script (copy `admin.overlay.example.json`). This can only **tighten** what bake already stamped (it cannot turn Hugging Face downloads on if bake left them off).
5. SentinelOne: unsigned → path allow `%ProgramFiles%\SwitchBay\**`. Signed `switchbay.exe` → import `sentinelone/SwitchBay-exclusions.json` (that exe, not `python.exe`).
6. Users open **Start → Switch Bay** (Edge app window on `http://127.0.0.1:8765`). First logon registers a per-user scheduled task via Active Setup. Copilot sign-in is Settings → GitHub Copilot (device flow / SSO).

Uninstall leaves `%LOCALAPPDATA%\switchbay` and `%USERPROFILE%\SwitchBay` (user data), same as VS Code.

### macOS — Jamf / MDM

1. Receive the `.pkg` from bake (notarize first if you want Gatekeeper-clean; MDM can install it unsigned).
2. Deploy the pkg. It installs:
   - `/Library/Application Support/SwitchBay/` (payload)
   - `/Library/LaunchAgents/com.switchbay.daemon.plist` (runs as the logged-in user)
   - `/Applications/Switch Bay.app` (opens Safari on the loopback UI)
3. Optional overlay: `/Library/Application Support/SwitchBay/admin.json` (tighten-only).
4. Users open **Switch Bay**. Copilot sign-in is Settings → GitHub Copilot.

---

## Bake machine (one command)

Do this on a blessed Windows 11 x64 box (for the MSI/Win32 layout) or an Apple-silicon Mac (for the pkg). Do **not** run it on employee laptops.

### 1. Download the CI tree

From the GitHub release (`v0.9.17` or newer):

- Windows: `switchbay-enterprise-win11-x64.zip`
- macOS: `switchbay-enterprise-darwin-arm64.tar.gz`

Unzip/untar. Smoke (optional): `serve.cmd` / `./serve.sh`, then open `http://127.0.0.1:8765`.

### 2. Stamp policy and assemble

On the bake machine, from a git checkout of Switch Bay **or** from the unpacked payload (the `scripts/` folder is in the repo; copy `scripts/bake_enterprise.py` next to the payload if you only have the zip):

```
python scripts/bake_enterprise.py ^
  --payload path\to\switchbay-enterprise-win11-x64 ^
  --copilot-host github.example.com ^
  --out dist\bake
```

macOS:

```
python3 scripts/bake_enterprise.py \
  --payload ./switchbay-enterprise-darwin-arm64 \
  --copilot-host github.example.com \
  --vendor-ce /path/to/curiosity-engine \
  --out dist/bake
```

Useful flags:

| Flag | Effect |
|---|---|
| `--copilot-host` | github.com or your GitHub Enterprise host (locked in Settings) |
| `--sso-slug` | EMU enterprise slug |
| `--allow-hf` | Allow Settings → Find & install for local models. **If you omit this, MDM cannot turn HF on later.** |
| `--no-skills-npx` | Disallow `npx` / `uvx skills add` |
| `--vendor-ce DIR` | Copy the curiosity-engine skill into `vendor/` so laptops never `npx` |

### 3. Optional: sign, then hand `dist/bake/` to IT

Unsigned MDM: give IT `dist/bake/` as-is. Company-signed: Authenticode / Developer ID + notarize; `NEXT.txt` lists the files. Windows without Visual Studio Build Tools still bakes; the task falls back to `python.exe` until you re-run bake with `cl` on PATH so `bin\switchbay.exe` exists (EDR prefers that host once you sign).

They follow **IT admin** above. They do not compile C, harvest WiX, or convert icons.

---

## Local test on a Mac (no pkg)

```
make enterprise-local    # gitignored admin.json, HF on, restart
make open-local          # back to consumer
```

---

## Policy (one rule)

`admin.baked.json` is the floor. MDM overlay **AND**s features: overlay can turn things off, not on.

To allow Hugging Face downloads on any laptop in the fleet, pass `--allow-hf` at bake.

Do not put policy in `%LOCALAPPDATA%\switchbay` or `~/.config/switchbay` (the daemon writes those).

---

## What CI still does not do

CI never holds a company cert. The release zip/tar is the *input* to bake, not the fleet package. There is no Intel Mac or Windows ARM payload.
