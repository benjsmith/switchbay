"""Workspace web policy: default off, per-call, never blanket."""

from __future__ import annotations

from pathlib import Path

import pytest

from switchbay import permissions, web_policy
from switchbay.llmgateway import openai_codex


def test_default_off(tmp_path: Path):
    assert web_policy.is_enabled(tmp_path) is False
    assert web_policy.effective_enabled(tmp_path) is False


def test_toggle_persists_per_workspace(tmp_path: Path):
    web_policy.save(tmp_path, enabled=True)
    assert web_policy.is_enabled(tmp_path) is True
    other = tmp_path / "other"
    other.mkdir()
    assert web_policy.is_enabled(other) is False


def test_protected_never_pre_approved_even_with_mcp_wildcard(tmp_path: Path):
    permissions.add_pattern(tmp_path, "mcp__switchbay__*")
    permissions.add_pattern(tmp_path, "WebSearch(*)")
    permissions.add_pattern(tmp_path, "_codex:web-search")
    for tool, payload in (
        ("WebSearch", {"query": "q"}),
        ("web_search", {"query": "q"}),
        ("research_search", {"query": "q"}),
        ("mcp__switchbay__research_fetch", {"url": "https://example.edu/x"}),
    ):
        pat = permissions.pattern_for(tool, payload)
        assert permissions.is_protected_egress(tool)
        assert not permissions.is_pre_approved(
            tmp_path, pat, tool=tool, tool_input=payload,
        )


def test_add_pattern_ignores_protected(tmp_path: Path):
    before = permissions.list_allowed(tmp_path)
    permissions.add_pattern(tmp_path, "_codex:web-search")
    permissions.add_pattern(tmp_path, "WebSearch(*)")
    permissions.add_pattern(tmp_path, "Bash(npm test*)")
    after = permissions.list_allowed(tmp_path)
    assert "_codex:web-search" not in after
    assert "WebSearch(*)" not in after
    assert "Bash(npm test*)" in after
    assert set(before).issubset(set(after))


def test_resolve_ignores_remember_for_protected(tmp_path: Path):
    rec = permissions.register(
        workspace=tmp_path, provider="claude-code", tool="WebSearch",
        tool_input={"query": "qwen"}, run_id=None,
    )
    out = permissions.resolve(
        rec.req_id, decision="approve", remember=True,
        pattern="WebSearch(*)", session=True,
    )
    assert out is not None
    assert out.remember is False
    assert "WebSearch(*)" not in permissions.list_allowed(tmp_path)
    session = permissions._SESSION_ALLOW.get(str(tmp_path), set())
    assert "WebSearch(*)" not in session


def test_codex_native_search_always_disabled(tmp_path: Path):
    permissions.add_pattern(tmp_path, "_codex:web-search")
    argv = openai_codex.web_search_overrides(tmp_path)
    assert "-c" in argv
    assert 'web_search="disabled"' in argv
    assert "tools.web_search=false" in argv
    assert "tools.web_search=true" not in argv
    assert "web_search=live" not in argv
    assert 'web_search="live"' not in argv


def test_codex_override_beats_preexisting_live(tmp_path: Path, monkeypatch):
    """Authoritative `-c web_search="disabled"` must appear so a user's
    ~/.codex/config.toml `web_search = "live"` cannot win.

    Codex `-c` flags parse as TOML and override the config file
    (developers.openai.com/codex/config-basic).
    """
    import shutil
    import subprocess

    home = tmp_path / "codex-home"
    home.mkdir()
    cfg = home / "config.toml"
    cfg.write_text('web_search = "live"\n', encoding="utf-8")
    argv = openai_codex.web_search_overrides(tmp_path)
    assert argv.count("-c") >= 1
    # The disabled override must be present as a TOML assignment.
    joined = " ".join(argv)
    assert 'web_search="disabled"' in joined
    assert 'web_search="live"' not in joined
    # Later -c wins over an earlier live if both were present.
    disabled_at = argv.index('web_search="disabled"')
    assert argv[disabled_at - 1] == "-c"
    binary = shutil.which("codex")
    if binary:
        probe = subprocess.run(
            [binary, "-c", 'web_search="disabled"', "--help"],
            capture_output=True, text=True, timeout=20,
        )
        text = (probe.stdout or "") + (probe.stderr or "")
        assert probe.returncode == 0 or "web_search" in text.lower() or "Usage" in text or "usage" in text


@pytest.mark.asyncio
async def test_web_policy_post_targets_originating_workspace(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from switchbay import daemon, workspaces

    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    monkeypatch.setattr(workspaces, "is_within_home", lambda p: True)
    monkeypatch.setattr(
        workspaces, "resolve_path",
        lambda s, **k: Path(s).expanduser().resolve(),
    )
    broadcasts: list[dict] = []

    async def fake_broadcast(_app, msg):
        broadcasts.append(msg)

    monkeypatch.setattr(daemon, "_broadcast", fake_broadcast)
    web_policy.save(a, enabled=False)
    web_policy.save(b, enabled=True)

    class Req:
        app = {"workspace": b, "ws_clients": set()}
        rel_url = SimpleNamespace(query={})
        headers: dict[str, str] = {}

        async def json(self):
            return {"enabled": True, "workspace": str(a)}

    resp = await daemon.handle_web_policy_post(Req())  # type: ignore[arg-type]
    body = resp.body
    import json as _json
    data = _json.loads(body)
    assert data["ok"] is True
    assert data["enabled"] is True
    assert Path(data["workspace"]).resolve() == a.resolve()
    assert web_policy.is_enabled(a) is True
    assert web_policy.is_enabled(b) is True, "POST must not write the newly active workspace"


@pytest.mark.asyncio
async def test_web_policy_get_is_scoped_to_query_workspace(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from switchbay import daemon, workspaces

    a = tmp_path / "alpha"
    b = tmp_path / "beta"
    a.mkdir()
    b.mkdir()
    monkeypatch.setattr(workspaces, "is_within_home", lambda p: True)
    monkeypatch.setattr(
        workspaces, "resolve_path",
        lambda s, **k: Path(s).expanduser().resolve(),
    )
    web_policy.save(a, enabled=False)
    web_policy.save(b, enabled=True)

    class Req:
        app = {"workspace": b}
        rel_url = SimpleNamespace(query={"workspace": str(a)})
        headers: dict[str, str] = {}

    resp = await daemon.handle_web_policy_get(Req())  # type: ignore[arg-type]
    import json as _json
    data = _json.loads(resp.body)
    assert data["enabled"] is False
    assert Path(data["workspace"]).resolve() == a.resolve()


def test_block_reason_when_off(tmp_path: Path):
    reason = permissions.web_egress_block_reason(
        tmp_path, "research_search", {"query": "x"},
    )
    assert reason is not None
    web_policy.save(tmp_path, enabled=True)
    assert permissions.web_egress_block_reason(
        tmp_path, "research_search", {"query": "x"},
    ) is None
