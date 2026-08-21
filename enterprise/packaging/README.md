# Enterprise packaging

Switch Bay is packaged once on a build host, then deployed with Intune
or Jamf. Endpoints do not run `uv`, `pnpm`, `npx`, or curiosity-engine
`setup.sh`.

Supported installers: **Windows 11 x64** and **macOS (Apple silicon)**.

| Role | Input | Output |
|---|---|---|
| **Packaging** | GitHub release archive (`switchbay-enterprise-*.zip` / `.tar.gz`) | `dist/bake/` (Windows layout and install scripts, or a macOS `.pkg`) |
| **Endpoint management** | That bake output, optionally code-signed | Intune Win32 app or Jamf package assigned to users |

---

## Packaging

Run these steps on a dedicated Windows 11 x64 host (Windows installer)
or an Apple silicon Mac (macOS installer)—not on employee laptops.

### 1. Obtain the release archive

From the GitHub release (**v0.9.17** or later):

- Windows: `switchbay-enterprise-win11-x64.zip`
- macOS: `switchbay-enterprise-darwin-arm64.tar.gz`

Extract the archive. Optional verification: `serve.cmd` or `./serve.sh`,
then open `http://127.0.0.1:8765`.

### 2. Apply policy and assemble the installer tree

Requires a Switch Bay checkout (for `scripts/bake_enterprise.py`) or a
copy of that script next to the extracted archive.

Windows:

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

| Flag | Effect |
|---|---|
| `--copilot-host` | `github.com` or the GitHub Enterprise host (locked in Settings) |
| `--sso-slug` | GitHub Enterprise Managed Users slug |
| `--allow-hf` | Permit Settings → Find & install for local models. If omitted, a later management overlay cannot enable it. |
| `--no-skills-npx` | Disallow `npx` / `uvx skills add` |
| `--vendor-ce DIR` | Copy the curiosity-engine skill into `vendor/` so endpoints do not fetch it with `npx` |

### 3. Code signing (optional)

`dist/bake/NEXT.txt` lists the binaries and packages to sign. Apply the
organization’s Authenticode process (Windows) or Developer ID and
notarization (macOS). Skip this step when deploying unsigned through
management (see **Trust models**).

If Visual Studio Build Tools are installed, bake produces
`bin\switchbay.exe` as the scheduled-task image. Otherwise the task
runs the bundled CPython interpreter. Allowlists should cover the
install directory in either case.

Hand `dist/bake/` to endpoint management. They do not compile native
code or author Windows Installer tables.

---

## Trust models

Both of the following use the same bake output and the same Intune or
Jamf fields. Code signing does not change Copilot, admin policy, or
loopback binding.

| | Management-deployed, unsigned | Organization-signed |
|---|---|---|
| Deployment | Intune or Jamf writes the tree under Program Files (Windows) or `/Library/Application Support/SwitchBay` (macOS). Allow the install path (and hash, if required) in endpoint detection. | The same install, after Authenticode or Developer ID + notarization on the bake output. |
| Typical use | Internal distribution on managed devices; no public download. | Required when security policy demands a signed line-of-business application, or when unmanaged Macs must pass Gatekeeper without prompts. |
| SentinelOne | Allow `%ProgramFiles%\SwitchBay\**` (and the macOS install directory). Do not exclude `python.exe` globally. | After `switchbay.exe` is signed, import `sentinelone/SwitchBay-exclusions.json` (that process, not `python.exe`). |

Management-installed files are not quarantined as browser downloads, so
unsigned binaries usually launch without Gatekeeper or SmartScreen
prompts on enrolled devices.

---

## Endpoint management

### Windows — Intune

1. Take `dist/bake/` from packaging.
2. If the tenant requires `.intunewin`, wrap the folder with
   `IntuneWinAppUtil.exe`.
3. **Apps → Windows → Add → Windows app (Win32)**.

| Field | Value |
|---|---|
| Install | `powershell.exe -ExecutionPolicy Bypass -File install.ps1` |
| Uninstall | `powershell.exe -ExecutionPolicy Bypass -File uninstall.ps1` |
| Detection | `detection.ps1` |
| Install behavior | **System** |
| Assignment | User group |
| Restart | No |

4. Optional: deploy `%ProgramData%\SwitchBay\admin.json` as a separate
   device configuration or script (`admin.overlay.example.json`). The
   overlay can only restrict baked policy; it cannot enable a flag that
   bake left off (including Hugging Face downloads).
5. SentinelOne: unsigned — allow `%ProgramFiles%\SwitchBay\**`. Signed
   `switchbay.exe` — import `sentinelone/SwitchBay-exclusions.json`.
6. Users start **Switch Bay** from the Start menu (Edge application
   window on `http://127.0.0.1:8765`). Active Setup registers a
   per-user scheduled task at first logon. Copilot authentication is
   Settings → GitHub Copilot (device flow or single sign-on).

Uninstall retains `%LOCALAPPDATA%\switchbay` and
`%USERPROFILE%\SwitchBay` (user data), consistent with Visual Studio
Code.

### macOS — Jamf and other management

1. Take the `.pkg` from bake. Notarize it if Gatekeeper-clean launch on
   unmanaged Macs is required; management can install an unsigned
   package on enrolled devices.
2. Deploy the package. It installs:
   - `/Library/Application Support/SwitchBay/` (application files)
   - `/Library/LaunchAgents/com.switchbay.daemon.plist` (runs as the
     logged-in user)
   - `/Applications/Switch Bay.app` (opens Safari on the local UI)
3. Optional overlay: `/Library/Application Support/SwitchBay/admin.json`
   (restricts baked policy only).
4. Users open **Switch Bay**. Copilot authentication is Settings →
   GitHub Copilot.

---

## Policy

`admin.baked.json` is the floor. A management overlay may turn features
off, not on.

To allow Hugging Face model downloads anywhere in the fleet, pass
`--allow-hf` at bake.

Do not store policy under `%LOCALAPPDATA%\switchbay` or
`~/.config/switchbay`; the daemon writes those locations.

---

## Developer check on a Mac (no package)

```
make enterprise-local    # repository-root admin.json (gitignored); Hugging Face downloads enabled
make open-local          # consumer profile
```

---

## Scope

GitHub Actions does not hold organization signing keys. Release archives
are packaging inputs, not the fleet installers. Intel Mac and Windows
ARM installers are not produced.
