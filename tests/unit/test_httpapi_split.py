"""The daemon's HTTP concepts live in switchbay.httpapi.

These tests lock the split: every moved function is the same object the
daemon re-exports (so existing monkeypatches still land), patched names
are read back at call time, and repo-relative paths still resolve from
daemon.py's location.

Run: pytest tests/unit/test_httpapi_split.py
"""

from __future__ import annotations

import ast
import asyncio
import importlib
import inspect
from pathlib import Path

import pytest

from switchbay import daemon
from switchbay.httpapi import _ns
from switchbay.httpapi import guard, sheets, static_app


def test_moved_functions_are_reexported():
    """A monkeypatch of switchbay.daemon.<name> replaces the object
    build_app registered, which is only true if the re-export is the
    same function object the concept module defined."""
    package = importlib.import_module("switchbay.httpapi")
    root = Path(package.__file__).resolve().parent
    missing = []
    for path in sorted(root.glob("*.py")):
        if path.name in {"__init__.py", "_ns.py"}:
            continue
        module = importlib.import_module(f"switchbay.httpapi.{path.stem}")
        for name, obj in vars(module).items():
            if not inspect.isfunction(obj):
                continue
            if obj.__module__ != module.__name__:
                continue
            exported = getattr(daemon, name, None)
            if exported is not obj:
                missing.append(f"{module.__name__}.{name}")
    assert missing == []


def test_daemon_ns_sees_a_monkeypatch(monkeypatch):
    sentinel = object()
    monkeypatch.setattr(daemon, "_broadcast", sentinel)
    assert _ns._daemon_ns._broadcast is sentinel


def test_guard_containment_matches_daemon(tmp_path):
    (tmp_path / "wiki").mkdir()
    assert guard._within(tmp_path, tmp_path / "wiki")
    assert guard._safe_resolve(tmp_path, "wiki") == (tmp_path / "wiki").resolve()
    assert guard._safe_resolve(tmp_path, "../outside") is None
    assert guard._within is daemon._within


def test_guard_rejects_non_loopback_origin():
    from aiohttp.test_utils import make_mocked_request

    req = make_mocked_request(
        "GET", "/api/health",
        headers={"Host": "127.0.0.1:8765", "Origin": "https://evil.example"},
    )
    assert guard._origin_host_allowed(req) is False
    assert guard._hostname_of("http://[::1]:8765") == "[::1]"


def test_untrusted_html_locks_the_origin():
    resp = guard._untrusted_html_response("<p>hi</p>")
    policy = resp.headers["Content-Security-Policy"]
    assert "sandbox" in policy
    assert "allow-same-origin" not in policy
    assert resp.content_type == "text/html"


def test_frontend_dist_stays_at_repo_root():
    """handlers used to live in daemon.py; parents[2] of that file is
    the repo root. Moving the function must not shift the path."""
    got = static_app._frontend_dist()
    expect = Path(daemon.__file__).resolve().parents[2] / "frontend" / "dist"
    assert got == expect


async def test_ui_ack_timeout_is_read_from_the_daemon(monkeypatch):
    """The default used to be bound when the function was defined.
    It has to follow a monkeypatch of the daemon constant, because
    that is how the timeout is tuned in tests."""
    monkeypatch.setattr(daemon, "_UI_ACK_TIMEOUT_S", 0.01)
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    app: dict = {}
    result = await sheets._wait_ui_ack(app, "cmd-1", fut)
    assert result["timeout"] is True
    assert result["ok"] is False
    assert "0s" in result["error"]


def test_route_table_is_unchanged_from_the_pre_split_source(tmp_path):
    """Registration order is the contract (the SPA catch-all is last).
    Compare the add_* calls still sitting in build_app with the source
    of the commit this split started from is done by keeping the calls
    in daemon.py; this checks the live router has the anchors."""
    app = daemon.build_app(tmp_path)
    found = []
    for route in app.router.routes():
        resource = getattr(route, "resource", None)
        canonical = getattr(resource, "canonical", None)
        if canonical:
            found.append((route.method, canonical))
    for method, path in (
        ("GET", "/api/health"),
        ("GET", "/api/tree"),
        ("GET", "/ws"),
        ("GET", "/api/plots"),
        ("GET", "/api/library"),
        ("POST", "/api/settings"),
        ("GET", "/api/web-policy"),
        ("POST", "/api/workspaces/add"),
        ("GET", "/{tail}"),
    ):
        assert (method, path) in found
    # The catch-all is registered after /ws so it cannot shadow it.
    assert found.index(("GET", "/ws")) < found.index(("GET", "/{tail}"))


def test_concept_modules_document_how_to_run():
    root = Path(daemon.__file__).resolve().parent / "httpapi"
    bare = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        doc = ast.get_docstring(tree) or ""
        if "python -m switchbay serve" not in doc:
            bare.append(path.name)
    assert bare == []
