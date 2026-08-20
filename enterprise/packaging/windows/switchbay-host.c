/*
 * Switch Bay CPython host — scheduled-task image.
 *
 * Not a rename of python.exe: new VERSIONINFO (see switchbay-host.rc).
 * python313.dll + python313._pth must sit next to this exe.
 * Company Authenticode-signs this binary and the adjacent DLL/.pyd.
 *
 * Build (MSVC): cl /nologo /O2 /Fe:switchbay.exe switchbay-host.c
 *               python313.lib user32.lib
 */
#define PY_SSIZE_T_CLEAN
#include <Python.h>

#ifdef _WIN32
#include <windows.h>
#endif

int main(int argc, char **argv)
{
    /* Console/CUI image for the Scheduled Task. GUI is SwitchBay.exe. */
    return Py_BytesMain(argc, argv);
}
