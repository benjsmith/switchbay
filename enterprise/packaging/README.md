# Enterprise packaging kit

Fleet-shaped layout. **CI produces unsigned trees.** The company
Authenticode-signs / notarizes on their bake machine.

## What packaging teams get

Release zip/tar (Win11 x64 / darwin arm64) plus this kit.

| Piece | Path |
|---|---|
| Frozen interpreter + site-packages | `python/cpython-*/` in the payload |
| Bake | payload `admin.baked.json` (tighten-only) |
| Overlay | `%ProgramData%\SwitchBay\admin.json` / `/Library/Application Support/SwitchBay/admin.json` |
| Windows host | `windows/switchbay-host.c` → `bin\switchbay.exe` |
| Windows GUI | `windows/switchbay-gui.c` → `bin\SwitchBay.exe` (Edge `--app=`) |
| WiX | `windows/SwitchBay.wxs` |
| Active Setup | `windows/register-user-task.ps1` + `SwitchBay.xml.template` |
| macOS stub | `macos/switchbay-stub.c` → Safari |
| macOS pkg | `macos/build-package.sh` (unsigned; notarize on bake machine) |
| Intune | `intune/win32-app.md` + `detection.ps1` |
| SentinelOne | `sentinelone/SwitchBay-exclusions.json` (`switchbay.exe`, not `python.exe`) |
| Harvest | `harvest.py` — fail if launchers still call uv/npx/setup.sh |

## Local Mac test (no pkg)

From a git checkout:

```
make enterprise-local   # overlay + restart; HF on so you can pull a small model
make open-local         # back to consumer
```

## Signing (company bake machine)

Windows: `signtool sign /fd SHA256 /tr http://timestamp.digicert.com bin\switchbay.exe bin\SwitchBay.exe bin\python313.dll bin\*.pyd`

macOS: `codesign --options runtime --entitlements macos/entitlements.plist` every dylib, then `notarytool submit`.

CI never holds the cert.
