"""Bake script stamps policy and assembles a Windows layout without cl.exe."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "bake_enterprise.py"


def _mod():
    spec = importlib.util.spec_from_file_location("bake_enterprise", _SCRIPTS)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _payload(tmp: Path) -> Path:
    p = tmp / "payload"
    (p / "src" / "switchbay").mkdir(parents=True)
    (p / "src" / "switchbay" / "__init__.py").write_text(
        '__version__ = "0.9.16"\n', encoding="utf-8",
    )
    (p / "frontend" / "dist").mkdir(parents=True)
    (p / "frontend" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    (p / "admin.baked.json").write_text(
        json.dumps({"profile": "enterprise", "features": {"hf_model_download": False}}),
        encoding="utf-8",
    )
    prefix = p / "python" / "cpython-3.13.2-windows-x86_64-none"
    prefix.mkdir(parents=True)
    (prefix / "python.exe").write_bytes(b"fake")
    (prefix / "python313.dll").write_bytes(b"dll")
    (prefix / "Lib").mkdir()
    (prefix / "Lib" / "site.py").write_text("#\n", encoding="utf-8")
    return p


def test_stamp_baked_allow_hf_and_host(tmp_path: Path):
    m = _mod()
    payload = _payload(tmp_path)
    data = m.stamp_baked(
        payload, copilot_host="ghe.example.com", sso_slug="acme",
        allow_hf=True, skills_npx=False,
    )
    on_disk = json.loads((payload / "admin.baked.json").read_text(encoding="utf-8"))
    assert on_disk == data
    assert data["copilot"]["host"] == "ghe.example.com"
    assert data["copilot"]["sso_slug"] == "acme"
    assert data["copilot"]["lock_host"] is True
    assert data["features"]["hf_model_download"] is True
    assert data["features"]["install_skills_npx"] is False
    assert data["allow_profile_override"] is False


def test_layout_windows_writes_serve_task(tmp_path: Path):
    m = _mod()
    payload = _payload(tmp_path)
    layout = tmp_path / "layout"
    notes = m.layout_windows(payload, layout)
    assert (layout / "serve-task.cmd").is_file()
    assert (layout / "bin" / "python313.dll").is_file()
    assert (layout / "bin" / "python313._pth").is_file()
    assert "src" in (layout / "bin" / "python313._pth").read_text(encoding="utf-8")
    assert (layout / "enterprise" / "packaging" / "windows" / "register-user-task.ps1").is_file()
    text = (layout / "serve-task.cmd").read_text(encoding="utf-8")
    assert "SWITCHBAY_PROFILE=enterprise" in text
    assert notes["host"] in ("python.exe fallback", "bin\\switchbay.exe")


def test_overlay_example_mentions_host():
    m = _mod()
    ex = m.overlay_example(copilot_host="ghe.example.com", allow_hf=False)
    assert ex["copilot"]["host"] == "ghe.example.com"
    assert ex["features"]["hf_model_download"] is False
