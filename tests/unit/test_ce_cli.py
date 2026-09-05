"""Fixed-argv CE CLI used by the Pi curator pack."""

from __future__ import annotations

import json
from pathlib import Path

from switchbay.ce_cli import main


def test_dry_run_wave_prime(tmp_path: Path, capsys):
    rc = main([
        "--workspace", str(tmp_path),
        "--tool", "ce_wave_prime",
        "--input", "{}",
        "--dry-run",
    ])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["dry_run"] is True
    assert out["tool"] == "ce_wave_prime"


def test_unknown_tool(tmp_path: Path, capsys):
    rc = main(["--workspace", str(tmp_path), "--tool", "not_a_tool", "--dry-run"])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False


def test_package_allowlist_rejects_other_tools(tmp_path: Path, capsys):
    rc = main([
        "--workspace", str(tmp_path),
        "--tool", "run_command",
        "--allow-tools", "search_wiki,read_wiki_page",
        "--dry-run",
    ])
    assert rc == 2
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert "allowlist" in out["error"]


def test_handler_ok_false_is_nonzero(tmp_path: Path, capsys, monkeypatch):
    monkeypatch.setattr(
        "switchbay.tools.execute",
        lambda *_a, **_k: {"ok": False, "error": "nope"},
    )
    rc = main([
        "--workspace", str(tmp_path),
        "--tool", "ce_wave_prime",
        "--input", "{}",
    ])
    assert rc == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["result"]["error"] == "nope"
