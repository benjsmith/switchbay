"""CLI / local provider availability: signed-in, not merely installed."""

from __future__ import annotations

import json
from pathlib import Path

from switchbay.llmgateway import claude_code, grok_build, llamacpp, muse_code, ollama, openai_codex


def test_claude_has_key_requires_oauth(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(claude_code.shutil, "which", lambda _b: "/usr/bin/claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(claude_code.Path, "home", classmethod(lambda cls: tmp_path))
    assert claude_code.has_key() is False

    (tmp_path / ".claude.json").write_text(
        json.dumps({"oauthAccount": {"emailAddress": "a@b.co", "accountUuid": "x"}}),
        encoding="utf-8",
    )
    assert claude_code.has_key() is True


def test_codex_has_key_requires_tokens(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(openai_codex.shutil, "which", lambda _b: "/usr/bin/codex")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(openai_codex.Path, "home", classmethod(lambda cls: tmp_path))
    assert openai_codex.has_key() is False
    d = tmp_path / ".codex"
    d.mkdir()
    (d / "auth.json").write_text(json.dumps({"tokens": {"access": "t"}}), encoding="utf-8")
    assert openai_codex.has_key() is True


def test_grok_has_key_requires_auth_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(grok_build, "grok_binary", lambda: "/usr/bin/grok")
    monkeypatch.setattr(grok_build.Path, "home", classmethod(lambda cls: tmp_path))
    assert grok_build.has_key() is False
    d = tmp_path / ".grok"
    d.mkdir()
    (d / "auth.json").write_text(json.dumps({"https://auth.x.ai::id": {"tok": 1}}), encoding="utf-8")
    assert grok_build.has_key() is True


def test_muse_has_key_requires_auth_marker(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(muse_code, "muse_binary", lambda: "/usr/bin/muse")
    monkeypatch.delenv("META_API_KEY", raising=False)
    monkeypatch.setattr(muse_code.Path, "home", classmethod(lambda cls: tmp_path))
    assert muse_code.has_key() is False
    monkeypatch.setenv("META_API_KEY", "x")
    assert muse_code.has_key() is True


def test_llamacpp_has_key_ignores_mlx_only_config(monkeypatch) -> None:
    monkeypatch.setattr(llamacpp.localllm, "load_config", lambda: {"backend": "mlx"})
    monkeypatch.setattr(
        "switchbay.local_models.list_installed",
        lambda: [{"backend": "mlx", "id": "qwen"}],
    )
    assert llamacpp.has_key() is False
    monkeypatch.setattr(
        "switchbay.local_models.list_installed",
        lambda: [{"backend": "llamacpp", "id": "ornith"}],
    )
    assert llamacpp.has_key() is True


def test_ollama_has_key_false_when_unreachable(monkeypatch) -> None:
    import urllib.request

    def _boom(*_a, **_k):
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", _boom)
    assert ollama.has_key() is False
