"""Enterprise payload stager: relocatable CPython + policy templates."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "stage_enterprise_payload.py"


def _mod():
    spec = importlib.util.spec_from_file_location("stage_enterprise_payload", _SCRIPTS)
    assert spec is not None and spec.loader is not None
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def _fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "src" / "switchbay").mkdir(parents=True)
    (repo / "src" / "switchbay" / "__init__.py").write_text(
        '__version__ = "0.0.0"\n', encoding="utf-8",
    )
    (repo / "frontend" / "dist").mkdir(parents=True)
    (repo / "frontend" / "dist" / "index.html").write_text("<html></html>", encoding="utf-8")
    (repo / "pyproject.toml").write_text("[project]\nname='switchbay'\n", encoding="utf-8")
    (repo / "uv.lock").write_text("# lock\n", encoding="utf-8")
    (repo / "LICENSE").write_text("FSL\n", encoding="utf-8")
    (repo / "README.md").write_text("# Switch Bay\n", encoding="utf-8")
    (repo / "config").mkdir()
    (repo / "config" / "admin.enterprise.json").write_text(
        '{"profile":"enterprise","features":{"hf_model_download":false}}\n',
        encoding="utf-8",
    )
    py_name = "cpython-3.13.2-macos-aarch64-none"
    prefix = tmp_path / "uv-python" / py_name
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "python3").write_text("#!/fake-python\n", encoding="utf-8")
    (prefix / "lib" / "python3.13" / "site-packages").mkdir(parents=True)
    venv = repo / ".venv"
    (venv / "lib" / "python3.13" / "site-packages" / "aiohttp").mkdir(parents=True)
    (venv / "lib" / "python3.13" / "site-packages" / "aiohttp" / "__init__.py").write_text(
        "# marker\n", encoding="utf-8",
    )
    (venv / "pyvenv.cfg").write_text(
        f"home = {prefix / 'bin'}\nversion_info = 3.13.2\n",
        encoding="utf-8",
    )
    return repo


def test_standalone_prefix_walks_to_cpython(tmp_path: Path):
    m = _mod()
    home = tmp_path / "cpython-3.13.2-macos-aarch64-none" / "bin"
    home.mkdir(parents=True)
    assert m.standalone_prefix(home).name.startswith("cpython-")


def test_stage_merges_site_packages_and_policy(tmp_path: Path):
    m = _mod()
    repo = _fake_repo(tmp_path)
    out = tmp_path / "payload"
    m.stage(repo, out)
    assert (out / "SWITCHBAY_PROFILE").read_text(encoding="utf-8").strip() == "enterprise"
    assert (out / "config" / "admin.enterprise.json").is_file()
    assert (out / "frontend" / "dist" / "index.html").is_file()
    assert (out / "serve.sh").is_file()
    assert (out / "serve.cmd").is_file()
    sp = (
        out / "python" / "cpython-3.13.2-macos-aarch64-none"
        / "lib" / "python3.13" / "site-packages" / "aiohttp" / "__init__.py"
    )
    assert sp.is_file()
    assert "hf_model_download" in (out / "PAYLOAD.txt").read_text(encoding="utf-8")
    assert (out / "admin.baked.json").is_file()
    assert '"profile": "enterprise"' in (out / "admin.baked.json").read_text(encoding="utf-8")


def test_stage_requires_frontend(tmp_path: Path):
    m = _mod()
    repo = _fake_repo(tmp_path)
    (repo / "frontend" / "dist" / "index.html").unlink()
    with pytest.raises(SystemExit, match="frontend/dist"):
        m.stage(repo, tmp_path / "payload")
