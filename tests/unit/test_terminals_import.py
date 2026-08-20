"""terminals.py must import on Windows (no top-level fcntl/pty)."""

from __future__ import annotations

from switchbay import terminals


def test_module_imports():
    assert hasattr(terminals, "pty_available")


def test_pty_available_matches_platform(monkeypatch):
    import sys
    if sys.platform == "win32":
        assert terminals.pty_available() is False
    else:
        assert terminals.pty_available() is True
