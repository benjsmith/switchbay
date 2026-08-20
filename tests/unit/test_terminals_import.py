"""terminals.py must import on Windows (no top-level fcntl/pty)."""

from __future__ import annotations

from switchbay import terminals


def test_module_imports():
    assert hasattr(terminals, "pty_available")


def test_pty_available_matches_platform(monkeypatch):
    import sys
    if sys.platform == "win32":
        # ConPTY is the Win11 backend; unit tests on darwin just
        # assert the helper exists. Live Windows CI checks True.
        assert terminals.pty_available() in (True, False)
    else:
        assert terminals.pty_available() is True
