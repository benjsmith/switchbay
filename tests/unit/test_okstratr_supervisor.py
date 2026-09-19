"""URL/port helpers + argv resolution for okstratr supervisor."""

from __future__ import annotations

from switchbay import okstratr_supervisor as oks


def test_upstream_defaults(monkeypatch):
    monkeypatch.delenv("SWITCHBAY_OKSTRATR_UPSTREAM", raising=False)
    assert oks.upstream_base() == "http://127.0.0.1:8767"
    assert oks.upstream_port() == 8767
    assert oks.upstream_host() == "127.0.0.1"
    assert oks.health_url().endswith("/health")


def test_upstream_env_override(monkeypatch):
    monkeypatch.setenv("SWITCHBAY_OKSTRATR_UPSTREAM", "http://127.0.0.1:9876")
    assert oks.upstream_base() == "http://127.0.0.1:9876"
    assert oks.upstream_port() == 9876


def test_resolve_argv_prefers_bin_override(monkeypatch, tmp_path):
    fake = tmp_path / "okstratr"
    fake.write_text("#!/bin/sh\n", encoding="utf-8")
    fake.chmod(0o755)
    monkeypatch.setenv("SWITCHBAY_OKSTRATR_BIN", str(fake))
    assert oks.resolve_okstratr_argv() == [str(fake)]


def test_resolve_argv_falls_back_to_module(monkeypatch):
    monkeypatch.delenv("SWITCHBAY_OKSTRATR_BIN", raising=False)
    monkeypatch.setattr(oks.shutil, "which", lambda _n: None)
    argv = oks.resolve_okstratr_argv()
    assert argv[-2:] == ["-m", "okstratr"]


def test_contract_slice_shape(monkeypatch):
    monkeypatch.setattr(oks, "is_healthy", lambda **_: False)
    monkeypatch.setattr(oks, "_read_pid", lambda: None)
    slice_ = oks.contract_slice()
    assert set(slice_) == {"state", "url", "detail"}
    assert slice_["state"] in {"starting", "healthy", "unhealthy", "stopped"}
