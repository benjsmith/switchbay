# Enterprise packaging kit

Fleet-shaped layout. **CI produces unsigned trees.** The company
Authenticode-signs / notarizes on their bake machine. Endpoints never
run `uv`, `pnpm`, `npx`, or curiosity-engine `setup.sh`.

## What packaging teams get

On each `v*` tag, GitHub Actions attaches:

| Asset | Runner | Contents |
|---|---|---|
| `switchbay-enterprise-win11-x64.zip` | `windows-latest` | Relocatable CPython + `src/` + `frontend/dist/` |
| `switchbay-enterprise-darwin-arm64.tar.gz` | `macos-14` | Same, Apple silicon only |

Plus this kit inside the tree (`enterprise/packaging/`).

| Piece | Path |
|---|---|
| Frozen interpreter + site-packages | `python/cpython-*/` in the payload |
| Bake (tighten-only) | payload `admin.baked.json` |
| Overlay (MDM) | `%ProgramData%\SwitchBay\admin.json` / `/Library/Application Support/SwitchBay/admin.json` |
| Windows host | `windows/switchbay-host.c` → `bin\switchbay.exe` |
| Windows GUI | `windows/switchbay-gui.c` → `bin\SwitchBay.exe` (Edge `--app=`) |
| WiX skeleton | `windows/SwitchBay.wxs` (host + Active Setup — **you harvest the rest**) |
| Active Setup | `windows/register-user-task.ps1` + `SwitchBay.xml.template` |
| macOS stub | `macos/switchbay-stub.c` → opens **Safari** |
| macOS pkg | `macos/build-package.sh` (unsigned; notarize on bake) |
| Intune | `intune/win32-app.md` + `detection.ps1` |
| SentinelOne | `sentinelone/SwitchBay-exclusions.json` (`switchbay.exe`, **not** `python.exe`) |
| Harvest | `harvest.py` — fail if launchers still call uv/npx/setup.sh |

Supported SKUs this release: **Win11 x64** and **macOS darwin arm64**.
No Intel Mac payload, no Windows ARM payload.

## Local Mac test (no pkg)

From a git checkout:

```
make enterprise-local   # overlay + restart; HF on so you can pull a small model
make open-local         # back to consumer
```

## SOC posture (what to tell the review)

Same class as VS Code Copilot on a laptop, over a curated wiki/graph:

- Per-user agent (LaunchAgent / InteractiveToken scheduled task), not a SYSTEM service.
- Binds **127.0.0.1:8765** only. Enterprise HTTP egress is Copilot/GHE (+ HF iff baked on).
- Copilot is device-flow OAuth (no long-lived API key in the package). HTTP tools only (`shell: false`); workspace commands still go through Switch Bay permission cards.
- Hosted LLM keys (Anthropic/OpenAI/xAI/Gemini/Meta) and coding CLIs are off.
- No `uv` / `pnpm` / `npx` / `setup.sh` at daemon start.
- In-app git pull is off; fleet updates are a new MSI/PKG.
- Interactive terminal is on (POSIX PTY / Win11 ConPTY) — same default as VS Code.
- `npx`/`uvx skills add` is **on** by default (VS Code parity); lock with `skills.allowlist`.
- MCP add is on; lock with `mcp.allowlist`.
- FSL-1.1-ALv2: internal use is in-scope. Competing Use (reselling Switch Bay) is not.

This is **not** a claim that CI-signed binaries exist. Unsigned zip/tar
will fail a serious SOC. The bake machine must sign.

## Bake machine playbook

Do **all** compile/sign/harvest on a blessed builder. Never `uv sync`
on an employee PC.

### 0. Smoke the CI tree first

Windows:

```
unzip switchbay-enterprise-win11-x64.zip
cd switchbay-enterprise-win11-x64
serve.cmd
# Edge: http://127.0.0.1:8765
```

macOS arm64:

```
tar -xzf switchbay-enterprise-darwin-arm64.tar.gz
cd switchbay-enterprise-darwin-arm64
./serve.sh
# Safari: http://127.0.0.1:8765
```

Run `python enterprise/packaging/harvest.py .` from the payload root.
Must print `harvest ok`.

### 1. Stamp policy **before** you freeze the image

`admin.baked.json` is copied from `config/admin.enterprise.json` at
stage time with `allow_profile_override: false` and `copilot.lock_host:
true`. **MDM overlay can only tighten features/providers** (AND). It
cannot turn a baked-off flag back on.

Consequences that surprise people:

| Want | Do this at bake | Overlay cannot |
|---|---|---|
| Hugging Face downloads later | `"hf_model_download": true` in **baked** | enable HF if baked is false |
| GitHub Enterprise / EMU host | `"copilot": { "host": "<ghe>", "sso_slug": "<emu>", "lock_host": true }` in baked (overlay *can* overwrite `copilot.host` today; still lock the Settings UI) | — |
| Disable `npx`/`uvx skills add` | `"install_skills_npx": false` or `skills.allowlist: []` | — |
| MCP allowlist | `mcp.allowlist` list of server ids | loosen a baked empty list if you AND |

Drop the MDM overlay at:

- Windows: `%ProgramData%\SwitchBay\admin.json` (root/SYSTEM, `644`)
- macOS: `/Library/Application Support/SwitchBay/admin.json` (root, `644`)

Do **not** put policy in `%LOCALAPPDATA%\switchbay` or
`~/.config/switchbay` — the daemon writes those.

### 2. Windows (Win11 x64) — the unusual bits

**Do not ship `python.exe` as the scheduled-task image** if you can
avoid it. EDR will flag persistent `python.exe`. Compile the C host:

```
# From payload, after copying python313.dll next to the host:
cl /nologo /O2 /Fe:bin\switchbay.exe enterprise\packaging\windows\switchbay-host.c python313.lib user32.lib
cl /nologo /O2 /Fe:bin\SwitchBay.exe enterprise\packaging\windows\switchbay-gui.c shell32.lib wininet.lib
```

`switchbay.exe` is a CPython embeddable host (`Py_BytesMain`). Layout
next to it **must** be:

```
<INSTALLDIR>\
  admin.baked.json
  SWITCHBAY_PROFILE          # contents: enterprise
  src\                       # required; _pth has ../src
  frontend\dist\
  python\cpython-*\          # full standalone (site-packages merged)
  bin\
    switchbay.exe
    SwitchBay.exe            # GUI: Edge --app=http://127.0.0.1:8765
    python313.dll
    python313.zip
    python313._pth           # from enterprise/packaging/windows/
    Lib\                     # or whatever _pth says; usually copy from cpython-*
  enterprise\packaging\      # Active Setup script + task XML live here
```

`python313._pth` paths are **relative to `bin\`**:

```
python313.zip
.
Lib
Lib/site-packages
../src
import site
```

If `src\` is not `INSTALLDIR\src`, or `Lib` is not beside the exe,
the task starts and silently dies.

**WiX `SwitchBay.wxs` is a skeleton** (host files + Active Setup
registry). You must **harvest** `src\`, `frontend\dist\`,
`python\`, `admin.baked.json`, `SWITCHBAY_PROFILE`, and
`enterprise\packaging\` into the MSI. The checked-in Feature does not
do that. There is **no `icon.ico`** in `frontend/dist` — convert
`icon-512.png` before `heat`.

**Active Setup, not a SYSTEM task.** The MSI is per-machine. The
daemon is per-user (`InteractiveToken`, `LeastPrivilege`).
`register-user-task.ps1` runs at first logon via Active Setup
`StubPath`. Do **not** wrap `python -m switchbay service install` as
the Intune install command. Do **not** register `schtasks` as SYSTEM.

On every MSI that needs existing users to re-run first-logon, **bump
the Active Setup `Version` registry value** (`1,0,0,0` → `1,0,1,0`).
Windows skips StubPath if the version does not increase.

Scheduled task exec (from the template):

```
Command:   <INSTALLDIR>\bin\switchbay.exe
Arguments: -m switchbay serve --workspace %USERPROFILE%\SwitchBay\workspace
WorkingDirectory: <INSTALLDIR>
```

Default workspace is `%USERPROFILE%\SwitchBay\workspace` (not synced).
IT may point `SWITCHBAY_WORKSPACE` at a known folder, including a
synced drive — that is an IT choice, not the default.

**Edge only** on Windows. `SwitchBay.exe` calls
`msedge --app=http://127.0.0.1:8765`. Chrome/Firefox are not the
enterprise shell.

**Sign on the bake machine** (CI never holds the cert):

```
signtool sign /fd SHA256 /tr http://timestamp.digicert.com ^
  bin\switchbay.exe bin\SwitchBay.exe bin\python313.dll bin\*.pyd
signtool sign /fd SHA256 /tr http://timestamp.digicert.com SwitchBay-<ver>-x64.msi
```

SentinelOne: import `sentinelone/SwitchBay-exclusions.json`. Exclude
the **signed host**, never `python.exe`. Until the host is signed, a
time-boxed path exclusion on the payload python is a **waiver**, not
this package.

Intune: `intune/win32-app.md`. Detection is file version of
`%ProgramFiles%\SwitchBay\bin\switchbay.exe` (from `switchbay-host.rc`).
Uninstall leaves `%LOCALAPPDATA%\switchbay` and `%USERPROFILE%\SwitchBay`
(user data), same as VS Code.

Stop is `taskkill /PID` of the daemon pidfile. Never
`taskkill /IM python.exe`.

### 3. macOS (darwin arm64)

```
enterprise/packaging/macos/build-package.sh \
  path/to/switchbay-enterprise-darwin-arm64 \
  dist/SwitchBay.pkg
```

The `.app` is a **stub**: it kickstarts `gui/$(id -u)/com.switchbay.daemon`
and `open -a Safari http://127.0.0.1:8765`. The real process is the
LaunchAgent running payload python `-m switchbay serve`.

Vendor the **curiosity-engine** skill onto the image (copy from the
builder). Set `SWITCHBAY_CE_ROOT` in the LaunchAgent environment so
the daemon never `npx skills add`. With `ce_auto_setup: false`, a
wiki without a CE `.venv` still opens; the graph is nodes-only until
IT provisions kuzu **on the builder** (or a workspace template).

**Notarize on the bake machine:**

```
codesign --sign "Developer ID Application: …" --options runtime \
  --entitlements enterprise/packaging/macos/entitlements.plist \
  --timestamp <every dylib and the stub>
# then productsign the pkg, notarytool submit, stapler staple
```

Hardened runtime is on; `disable-library-validation` is **false**.
Do not mix unsigned wheels into the payload after sign.

LaunchAgent program is payload `python/cpython-*/bin/python3`, not
`uv run`. KeepAlive is per-user, not a privileged daemon.

Safari (or the PWA) is the UI. There is no signed WKWebView wrapper
in this kit.

### 4. Updates

`features.in_app_update` is off. Ship a new MSI/PKG. Do not enable
Settings → Update on the fleet (it is `git pull` / `npx` as the user).

### 5. What local admins can still do

A machine-local Administrator can replace `%ProgramData%` /
`/Library/Application Support` overlay. Baked flags they try to
*loosen* stay off (AND). They can still kill the task, replace the
tree, or set `SWITCHBAY_ADMIN_POLICY` at process start if they control
the task XML. **Not admin-proof** — same as VS Code user-install plus
a system overlay. Document that for SOC; don't claim otherwise.

## Signing (company bake machine)

Windows: `signtool sign /fd SHA256 /tr http://timestamp.digicert.com bin\switchbay.exe bin\SwitchBay.exe bin\python313.dll bin\*.pyd`

macOS: `codesign --options runtime --entitlements macos/entitlements.plist` every dylib, then `notarytool submit`.

CI never holds the cert.
