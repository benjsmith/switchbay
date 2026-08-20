# Intune Win32 app (import this with the signed MSI)

| Field | Value |
|---|---|
| Name | Switch Bay |
| Publisher | Switch Bay (company-signed) |
| App version | 0.9.16 |
| Install | `msiexec /i SwitchBay-0.9.16-x64.msi /qn ALLUSERS=1` |
| Uninstall | `msiexec /x {PRODUCTCODE} /qn` |
| Detection | `enterprise/packaging/intune/detection.ps1` — file `%ProgramFiles%\SwitchBay\bin\switchbay.exe` version ≥ 0.9.16 |
| Install behavior | System |
| Assignment | Required or available, user group |
| Restart | No |

Uninstall **leaves** `%LOCALAPPDATA%\switchbay` and `%USERPROFILE%\SwitchBay` (user data). Same as VS Code.

Do **not** wrap `python -m switchbay service install` as the Intune command.
