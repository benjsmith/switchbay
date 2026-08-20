"""Windows ConPTY backend for the rail terminal.

Uses the Win32 ``CreatePseudoConsole`` API (Windows 10 1809+; our
floor is Win11). That API is part of the OS — no third-party PTY
library, no extra license. VS Code uses the same facility.

asyncio's ProactorEventLoop cannot ``add_reader`` a pipe, so output
is pumped on a daemon thread into an asyncio queue.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import signal
import sys
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("switchbay.terminals.win")

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    HPCON = wintypes.HANDLE
    S_OK = 0
    EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    CREATE_UNICODE_ENVIRONMENT = 0x00000400
    PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
    HANDLE_FLAG_INHERIT = 0x00000001
    STARTF_USESTDHANDLES = 0x00000100

    class COORD(ctypes.Structure):
        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", STARTUPINFOW),
            ("lpAttributeList", ctypes.c_void_p),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    class SECURITY_ATTRIBUTES(ctypes.Structure):
        _fields_ = [
            ("nLength", wintypes.DWORD),
            ("lpSecurityDescriptor", ctypes.c_void_p),
            ("bInheritHandle", wintypes.BOOL),
        ]

    kernel32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE), ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(SECURITY_ATTRIBUTES), wintypes.DWORD,
    ]
    kernel32.CreatePipe.restype = wintypes.BOOL
    kernel32.SetHandleInformation.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD]
    kernel32.SetHandleInformation.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.CreatePseudoConsole.argtypes = [
        COORD, wintypes.HANDLE, wintypes.HANDLE, wintypes.DWORD,
        ctypes.POINTER(HPCON),
    ]
    kernel32.CreatePseudoConsole.restype = ctypes.HRESULT
    kernel32.ResizePseudoConsole.argtypes = [HPCON, COORD]
    kernel32.ResizePseudoConsole.restype = ctypes.HRESULT
    kernel32.ClosePseudoConsole.argtypes = [HPCON]
    kernel32.ClosePseudoConsole.restype = None
    kernel32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p, wintypes.DWORD, ctypes.c_size_t, ctypes.c_void_p,
        ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p,
    ]
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel32.DeleteProcThreadAttributeList.argtypes = [ctypes.c_void_p]
    kernel32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR, wintypes.LPWSTR, ctypes.c_void_p, ctypes.c_void_p,
        wintypes.BOOL, wintypes.DWORD, ctypes.c_void_p, wintypes.LPCWSTR,
        ctypes.POINTER(STARTUPINFOEXW), ctypes.POINTER(PROCESS_INFORMATION),
    ]
    kernel32.CreateProcessW.restype = wintypes.BOOL
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    kernel32.TerminateProcess.restype = wintypes.BOOL
    kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    kernel32.WaitForSingleObject.restype = wintypes.DWORD
    kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    kernel32.GetExitCodeProcess.restype = wintypes.BOOL


@dataclass
class WinConPTY:
    hpcon: Any
    read_handle: Any
    write_handle: Any
    process: Any
    thread: Any
    attr_list: Any
    pid: int


def conpty_available() -> bool:
    if sys.platform != "win32":
        return False
    return hasattr(kernel32, "CreatePseudoConsole")


def default_shell() -> list[str]:
    for name in ("pwsh.exe", "powershell.exe"):
        found = shutil.which(name)
        if found:
            return [found, "-NoLogo"]
    return [os.environ.get("COMSPEC") or "cmd.exe"]


def _pipe_pair() -> tuple[Any, Any]:
    sa = SECURITY_ATTRIBUTES()
    sa.nLength = ctypes.sizeof(sa)
    sa.bInheritHandle = True
    sa.lpSecurityDescriptor = None
    r = wintypes.HANDLE()
    w = wintypes.HANDLE()
    if not kernel32.CreatePipe(ctypes.byref(r), ctypes.byref(w), ctypes.byref(sa), 0):
        raise OSError("CreatePipe failed")
    return r, w


def spawn_conpty(
    *,
    cwd: Path,
    argv: list[str],
    env: dict[str, str],
    rows: int,
    cols: int,
) -> WinConPTY:
    if not conpty_available():
        raise RuntimeError("ConPTY is not available on this Windows build")

    # Our write end → PTY input; PTY output → our read end.
    pty_in, our_write = _pipe_pair()
    our_read, pty_out = _pipe_pair()
    kernel32.SetHandleInformation(our_write, HANDLE_FLAG_INHERIT, 0)
    kernel32.SetHandleInformation(our_read, HANDLE_FLAG_INHERIT, 0)

    hpcon = HPCON()
    size = COORD(cols, rows)
    hr = kernel32.CreatePseudoConsole(size, pty_in, pty_out, 0, ctypes.byref(hpcon))
    kernel32.CloseHandle(pty_in)
    kernel32.CloseHandle(pty_out)
    if hr != S_OK:
        kernel32.CloseHandle(our_read)
        kernel32.CloseHandle(our_write)
        raise OSError(f"CreatePseudoConsole failed HRESULT=0x{hr & 0xFFFFFFFF:08X}")

    size_attr = ctypes.c_size_t()
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size_attr))
    buf = (ctypes.c_byte * size_attr.value)()
    if not kernel32.InitializeProcThreadAttributeList(buf, 1, 0, ctypes.byref(size_attr)):
        kernel32.ClosePseudoConsole(hpcon)
        raise OSError("InitializeProcThreadAttributeList failed")
    hpcon_storage = HPCON(hpcon)
    if not kernel32.UpdateProcThreadAttribute(
        buf, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
        ctypes.byref(hpcon_storage), ctypes.sizeof(HPCON), None, None,
    ):
        kernel32.DeleteProcThreadAttributeList(buf)
        kernel32.ClosePseudoConsole(hpcon)
        raise OSError("UpdateProcThreadAttribute failed")

    siex = STARTUPINFOEXW()
    siex.StartupInfo.cb = ctypes.sizeof(STARTUPINFOEXW)
    siex.lpAttributeList = ctypes.cast(buf, ctypes.c_void_p)

    pi = PROCESS_INFORMATION()
    cmdline = subprocess_list2cmdline(argv)
    env_block = _env_block(env)
    if not kernel32.CreateProcessW(
        None, ctypes.c_wchar_p(cmdline), None, None, False,
        EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT,
        env_block, str(cwd), ctypes.byref(siex), ctypes.byref(pi),
    ):
        err = ctypes.get_last_error()
        kernel32.DeleteProcThreadAttributeList(buf)
        kernel32.ClosePseudoConsole(hpcon)
        raise OSError(f"CreateProcessW failed ({err})")
    kernel32.CloseHandle(pi.hThread)
    return WinConPTY(
        hpcon=hpcon,
        read_handle=our_read,
        write_handle=our_write,
        process=pi.hProcess,
        thread=None,
        attr_list=buf,
        pid=int(pi.dwProcessId),
    )


def subprocess_list2cmdline(argv: list[str]) -> str:
    import subprocess
    return subprocess.list2cmdline(argv)


def _env_block(env: dict[str, str]) -> Any:
    # UTF-16LE NUL-separated key=value pairs, double-NUL terminated.
    parts = [f"{k}={v}" for k, v in env.items()]
    blob = "\0".join(parts) + "\0\0"
    return ctypes.create_unicode_buffer(blob)


def write(con: WinConPTY, data: bytes) -> None:
    n = wintypes.DWORD()
    if not data:
        return
    buf = ctypes.create_string_buffer(data, len(data))
    kernel32.WriteFile(con.write_handle, buf, len(data), ctypes.byref(n), None)


def resize(con: WinConPTY, rows: int, cols: int) -> None:
    kernel32.ResizePseudoConsole(con.hpcon, COORD(cols, rows))


def terminate(con: WinConPTY) -> None:
    try:
        kernel32.TerminateProcess(con.process, 1)
    except Exception:  # noqa: BLE001
        pass


def wait_exit(con: WinConPTY, timeout_ms: int = 5000) -> int | None:
    kernel32.WaitForSingleObject(con.process, timeout_ms)
    code = wintypes.DWORD()
    if kernel32.GetExitCodeProcess(con.process, ctypes.byref(code)):
        return int(code.value)
    return None


def close(con: WinConPTY) -> None:
    try:
        kernel32.ClosePseudoConsole(con.hpcon)
    except Exception:  # noqa: BLE001
        pass
    for h in (con.read_handle, con.write_handle, con.process):
        try:
            kernel32.CloseHandle(h)
        except Exception:  # noqa: BLE001
            pass
    try:
        kernel32.DeleteProcThreadAttributeList(con.attr_list)
    except Exception:  # noqa: BLE001
        pass


def start_read_thread(con: WinConPTY, loop: asyncio.AbstractEventLoop, queue: asyncio.Queue) -> None:
    chunk = 16 * 1024

    def _run() -> None:
        buf = ctypes.create_string_buffer(chunk)
        nread = wintypes.DWORD()
        while True:
            ok = kernel32.ReadFile(con.read_handle, buf, chunk, ctypes.byref(nread), None)
            if not ok or nread.value == 0:
                loop.call_soon_threadsafe(queue.put_nowait, None)
                return
            data = buf.raw[: nread.value]
            loop.call_soon_threadsafe(queue.put_nowait, data)

    t = threading.Thread(target=_run, name="conpty-read", daemon=True)
    con.thread = t
    t.start()
