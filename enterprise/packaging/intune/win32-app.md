# Intune Win32 app

Import **after** `scripts/bake_enterprise.py` and Authenticode sign.
Use the `dist/bake/` folder (layout + install.ps1). This is the VS Code
motion: IT imports an installer; they do not compile the product.

| Field | Value |
|---|---|
| Name | Switch Bay |
| Publisher | Switch Bay (company-signed) |
| App version | 0.9.18 |
| Install | `powershell.exe -ExecutionPolicy Bypass -File install.ps1` |
| Uninstall | `powershell.exe -ExecutionPolicy Bypass -File uninstall.ps1` |
| Detection | `detection.ps1` — `%ProgramFiles%\SwitchBay\bin\switchbay.exe` version ≥ 0.9.18 (or `python.exe` in that folder if bake used the fallback host) |
| Install behavior | System |
| Assignment | Required or available, user group |
| Restart | No |

Uninstall **leaves** `%LOCALAPPDATA%\switchbay` and `%USERPROFILE%\SwitchBay` (user data). Same as VS Code.

Do **not** use `python -m switchbay service install` as the Intune command.
