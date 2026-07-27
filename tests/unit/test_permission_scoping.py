"""Permission cards are scoped to the rail thread that owns the
requesting CLI session; external sessions (bench runs, scripts) carry
an origin label and their bookkeeping targets the ORIGIN workspace —
so parallel CLI sessions can't bleed into an open thread's transcript
or pollute the focused workspace's allow-list."""

from __future__ import annotations

import json

from switchbay import permissions, protocol
from switchbay.llmgateway import claude_code_settings


def _register(tmp_path, **kw):
    defaults = dict(
        workspace=tmp_path, provider="claude-code", tool="Bash",
        tool_input={"command": "echo done"}, run_id="sess-1",
    )
    defaults.update(kw)
    return permissions.register(**defaults)


def test_register_carries_thread_and_origin(tmp_path):
    rec = _register(tmp_path, thread_id="th-42", origin=None)
    try:
        assert rec.thread_id == "th-42"
        assert rec.origin is None
    finally:
        permissions.resolve(rec.req_id, decision="deny", remember=False)


def test_register_defaults_to_unowned(tmp_path):
    rec = _register(tmp_path)
    try:
        assert rec.thread_id is None
        assert rec.origin is None
    finally:
        permissions.resolve(rec.req_id, decision="deny", remember=False)


def test_external_remember_writes_origin_workspace_allowlist(tmp_path):
    origin_ws = tmp_path / "bench-ws"
    origin_ws.mkdir()
    rec = _register(origin_ws, thread_id=None, origin="~/bench-ws")
    permissions.resolve(rec.req_id, decision="approve", remember=True)
    assert rec.pattern in permissions.list_allowed(origin_ws)
    assert rec.pattern not in permissions.list_allowed(tmp_path)


def test_protocol_payload_carries_scope_fields():
    msg = protocol.permission_request(
        req_id="r1", provider="claude-code", tool="Bash",
        tool_input={"command": "true"}, pattern="Bash(true)",
        run_id="sess-1", thread_id=None, origin="~/x",
    )
    assert msg["value"]["thread_id"] is None
    assert msg["value"]["origin"] == "~/x"
    owned = protocol.permission_request(
        req_id="r2", provider="claude-code", tool="Bash",
        tool_input={"command": "true"}, pattern="Bash(true)",
        run_id="sess-2", thread_id="th-1", origin=None,
    )
    assert owned["value"]["thread_id"] == "th-1"


def test_hook_forwards_cwd_and_origin_thread(tmp_path):
    """The generated PreToolUse hook must forward the CLI session's cwd
    and the daemon-exported CSWY_THREAD_ID so the daemon can attribute
    the request. String-level check on the template keeps this honest
    without spawning a subprocess."""
    body = claude_code_settings._PERMISSION_HOOK_BODY
    assert '"cwd"' in body
    assert "CSWY_THREAD_ID" in body
    assert '"origin_thread"' in body
    # And the written hook matches the template.
    p = claude_code_settings.write_permission_hook(tmp_path)
    assert p.read_text(encoding="utf-8") == body


def test_settings_still_wire_the_hook(tmp_path):
    cfg = claude_code_settings.build_settings(tmp_path, 8765)
    hooks = json.dumps(cfg["hooks"])
    assert "permission-hook.py" in hooks


def _run_hook(tmp_path, payload, *, port, env=None):
    """Execute the generated hook script against a payload and return
    its parsed stdout JSON. `port` should point at nothing so the
    daemon POST fails fast (connection refused) — that exercises the
    fail-open (claude) vs fail-closed (grok) split without a server."""
    import subprocess
    import sys

    script = tmp_path / "hook.py"
    script.write_text(claude_code_settings._PERMISSION_HOOK_BODY, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(script), str(port)],
        input=json.dumps(payload).encode(),
        capture_output=True, timeout=30,
        env={**__import__("os").environ, **(env or {})},
    )
    return json.loads(proc.stdout.decode() or "{}")


def test_hook_claude_daemon_unreachable_falls_through(tmp_path):
    # claude-code has its own static allowlist as a backstop, so an
    # unreachable daemon → {} (no override), NOT a blanket deny.
    out = _run_hook(tmp_path, {
        "tool_name": "Bash", "tool_input": {"command": "ls"},
        "session_id": "s1", "cwd": str(tmp_path),
    }, port=1)
    assert out == {}


def test_hook_grok_daemon_unreachable_fails_closed(tmp_path):
    # grok FAILS OPEN on a silent hook, so an unreachable daemon must
    # produce an explicit deny — never an empty/allow response.
    out = _run_hook(tmp_path, {
        "toolName": "run_terminal_command", "toolInput": {"command": "ls"},
        "sessionId": "s1", "workspaceRoot": str(tmp_path),
    }, port=1)
    assert out.get("decision") == "deny"


def test_hook_empty_tool_is_passthrough(tmp_path):
    # claude dialect, no tool name → {} (nothing to adjudicate).
    out = _run_hook(tmp_path, {"tool_name": "", "tool_input": {}}, port=1)
    assert out == {}


def test_register_carries_origin_path(tmp_path):
    rec = _register(tmp_path, thread_id=None, origin="~/bench",
                    origin_path=str(tmp_path))
    try:
        assert rec.origin_path == str(tmp_path)
    finally:
        permissions.resolve(rec.req_id, decision="skip", remember=False)


def test_resolve_skip_does_not_write_allowlist(tmp_path):
    rec = _register(tmp_path, thread_id=None, origin="~/bench")
    permissions.resolve(rec.req_id, decision="skip", remember=True)
    # skip is not an approval — nothing is remembered.
    assert permissions.list_allowed(tmp_path) == []
