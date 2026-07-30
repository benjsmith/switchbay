r"""Every module byte-compiles without a SyntaxWarning.

`uv sync` / the service install byte-compile the package, so a stray
backslash escape (`\d`, `` \` ``) in a non-raw docstring surfaces as a
scary "SyntaxError: invalid escape sequence" line in the middle of an
otherwise-clean install. Cheap to guard, easy to regress.
"""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "switchbay"


def _modules() -> list[Path]:
    return sorted(p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts)


def test_source_tree_is_non_empty() -> None:
    assert len(_modules()) > 20


@pytest.mark.parametrize("path", _modules(), ids=lambda p: p.name)
def test_module_compiles_without_warnings(path: Path) -> None:
    source = path.read_text(encoding="utf-8")
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        compile(source, str(path), "exec")
    problems = [
        f"{w.category.__name__}: {w.message}"
        for w in caught
        if issubclass(w.category, SyntaxWarning)
    ]
    assert not problems, f"{path.relative_to(SRC)} → {problems}"
