"""The locked install includes kuzu so the first graph rebuild can import it."""

from __future__ import annotations

import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_kuzu_is_pinned_in_pyproject_and_lock() -> None:
    pyproject = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    deps = pyproject["project"]["dependencies"]
    assert "kuzu==0.11.3" in deps
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert 'name = "kuzu"' in lock
    assert 'version = "0.11.3"' in lock


def test_kuzu_imports_in_this_interpreter() -> None:
    # CI runs this after `uv sync --locked`. A lockfile that names kuzu
    # but a sync that skipped it fails here, which is the fresh-install
    # failure (`kuzu not installed` on the first graph rebuild).
    import kuzu

    assert kuzu.Database
