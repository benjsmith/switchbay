"""The version the app reports must be the version that was released.

`switchbay.__version__` feeds Help → versions and the GitHub update
check. It sat at 0.12.1 through five releases because the release
checklist bumped pyproject.toml, package.json and the docs but not this
constant — so a current install reported itself as ancient and the
updater kept offering it releases it was already past.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import switchbay

REPO = Path(__file__).resolve().parents[2]


def _pyproject_version() -> str:
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, "pyproject.toml has no top-level version"
    return m.group(1)


def test_dunder_version_matches_pyproject():
    assert switchbay.__version__ == _pyproject_version()


def test_frontend_version_matches_pyproject():
    pkg = json.loads(
        (REPO / "frontend" / "package.json").read_text(encoding="utf-8"),
    )
    assert pkg["version"] == _pyproject_version()


def test_changelog_leads_with_this_version():
    text = (REPO / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(r"^## .*?—\s*v(\d+\.\d+\.\d+)", text, re.M)
    assert m, "CHANGELOG.md has no versioned release heading"
    assert m.group(1) == _pyproject_version(), (
        "the newest CHANGELOG entry is not this version — either the "
        "release notes or the version bump was forgotten"
    )


def test_reported_version_is_the_running_one():
    # updater.local_switchbay_version is what /api/versions serves.
    out = subprocess.run(
        [sys.executable, "-c",
         "from switchbay import updater; print(updater.local_switchbay_version())"],
        capture_output=True, text=True, check=True, cwd=REPO,
        env={**os.environ, "PYTHONPATH": str(REPO / "src")},
    )
    assert out.stdout.strip() == _pyproject_version()
