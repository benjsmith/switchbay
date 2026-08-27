"""Agent Dashboard wave-status file (VS Code has no Chat done-hook)."""

from __future__ import annotations

from pathlib import Path

from switchbay import orchestration_report, tools


def test_report_writes_state_file(tmp_path: Path) -> None:
    out = orchestration_report.write_report(tmp_path, {
        "phase": "done",
        "detail": "OBJECTIVE_MET: yes",
        "objective_met": "yes",
    })
    assert out["ok"] is True
    path = tmp_path / ".workbench" / "state" / "orchestration-report.json"
    assert path.is_file()
    assert out["phase"] == "done"
    assert "OBJECTIVE_MET" in out["detail"]


def test_report_rejects_bad_phase(tmp_path: Path) -> None:
    out = orchestration_report.write_report(tmp_path, {"phase": "maybe"})
    assert out["ok"] is False


def test_mcp_activity_heartbeat(tmp_path: Path) -> None:
    import json
    from switchbay.mcp_server import write_mcp_activity

    write_mcp_activity(tmp_path, "search_wiki", {"query": "piriform cortex"})
    path = tmp_path / ".workbench" / "state" / "mcp-activity.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["tool"] == "search_wiki"
    assert "piriform" in data["detail"]


def test_tool_is_registered() -> None:
    assert "orchestration_report" in tools.REGISTRY
    spec = tools.REGISTRY["orchestration_report"].to_anthropic()
    assert spec["input_schema"]["required"] == ["phase"]
