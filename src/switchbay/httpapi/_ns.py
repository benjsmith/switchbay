"""Call-time lookup of names on ``switchbay.daemon``.

Handlers live in concept modules, but unit tests monkeypatch helpers
on the daemon module. Reading them here at call time keeps those
patches effective without a cycle while the daemon is importing.

Run: python -m switchbay serve --workspace PATH
"""

from __future__ import annotations


class _DaemonNs:
    """Attribute access resolves on switchbay.daemon at call time."""

    def __getattr__(self, name: str):
        import switchbay.daemon as daemon

        return getattr(daemon, name)


_daemon_ns = _DaemonNs()
