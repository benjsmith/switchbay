"""CE host glue: wiki commit, wave prime, worker templates, score_diff body."""

from __future__ import annotations

import json
from pathlib import Path

from switchbay import ce_host, ce_tools, plugin_tools, tools
from switchbay.agents import rail_default


def test_new_ce_host_tools_registered_and_allowed():
    for n in (
        "ce_wiki_commit", "ce_evolve_guard", "ce_wave_prime",
        "ce_dispatch_worker",
    ):
        assert n in tools.REGISTRY
        assert n in rail_default.ALLOWED_TOOLS
        assert n in plugin_tools.ALLOWED_TOOLS
    assert "run_command" not in plugin_tools.ALLOWED_TOOLS


def test_wiki_commit_requires_message_and_repo(tmp_path: Path):
    out = ce_host.wiki_commit(tmp_path, {})
    assert out.get("ok") is False
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    out = ce_host.wiki_commit(tmp_path, {"message": "curate: test"})
    assert out.get("ok") is False
    assert "git" in str(out.get("error") or "").lower()


def test_wiki_commit_happy(tmp_path: Path):
    import subprocess
    wiki = tmp_path / "wiki"
    wiki.mkdir()
    subprocess.run(["git", "init"], cwd=wiki, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=wiki, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=wiki, check=True)
    (wiki / "hello.md").write_text("hi\n", encoding="utf-8")
    out = ce_host.wiki_commit(tmp_path, {"message": "curate: hello"})
    assert out.get("ok") is True
    assert out.get("committed") is True


def test_score_diff_passes_new_text_file(tmp_path: Path, monkeypatch):
    seen: dict = {}

    def fake_run(script, args=None, *, cwd, timeout=120.0, require_json=True):
        seen["script"] = script
        seen["args"] = list(args or [])
        return {"accept": True, "applied": True}

    monkeypatch.setattr("switchbay.cebridge.run_script", fake_run)
    (tmp_path / ".curator").mkdir()
    out = tools.REGISTRY["ce_score_diff"].handler(tmp_path, {
        "page": "wiki/concepts/x.md",
        "new_text": "# X\n\nhello (vault:a.md)\n",
        "new_page": True,
    })
    assert seen["script"] == "score_diff.py"
    assert "--new-text-file" in seen["args"]
    assert "--new-page" in seen["args"]
    idx = seen["args"].index("--new-text-file")
    path = Path(seen["args"][idx + 1])
    assert path.read_text(encoding="utf-8").startswith("# X")
    assert out.get("accept") is True


def test_sweep_verdict_bypasses_safe_args(tmp_path: Path, monkeypatch):
    seen: dict = {}

    def fake_run(script, args=None, *, cwd, timeout=180.0, require_json=False):
        seen["args"] = list(args or [])
        return {"ok": True}

    monkeypatch.setattr("switchbay.cebridge.run_script", fake_run)
    verdict = {
        "page": "wiki/tables/tab-x.md",
        "verdict": "ok",
        "flagged_cells": [],
        "notes": "line1\nline2 <cell>",
    }
    tools.REGISTRY["ce_sweep"].handler(tmp_path, {
        "verb": "apply-numeric-review",
        "tab_page": "wiki/tables/tab-x.md",
        "verdict": verdict,
    })
    assert "apply-numeric-review" in seen["args"]
    assert "--tab-page" in seen["args"]
    assert "--verdict-json" in seen["args"]
    raw = seen["args"][seen["args"].index("--verdict-json") + 1]
    parsed = json.loads(raw)
    assert parsed["notes"].startswith("line1")


def test_extract_prompt_section():
    text = "## figure_extractor (worker-model)\n\nhi\n\n## other\n\nbye\n"
    sec = ce_host.extract_prompt_section(text, "figure_extractor")
    assert sec is not None
    assert "hi" in sec
    assert "bye" not in sec


def test_dispatch_worker_plugin_does_not_complete(tmp_path: Path, monkeypatch):
    prompts = tmp_path / ".curator"
    prompts.mkdir()
    (prompts / "prompts.md").write_text(
        "## numeric_transcription_review (reviewer-model)\n\n"
        "Tab page: <TAB_PAGE_PATH>\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("CSWY_PROFILE", "vscode")
    out = ce_host.dispatch_worker(tmp_path, {
        "role": "numeric_transcription_review",
        "substitutions": json.dumps({"TAB_PAGE_PATH": "wiki/tables/t.md"}),
    })
    assert out.get("ok")
    assert out.get("agent") == "NumericReviewer"
    assert "wiki/tables/t.md" in out.get("prompt", "")
    assert "text" not in out
    assert out.get("launched") is False
    assert "does not launch" in (out.get("note") or "").lower() or "not launch" in (out.get("note") or "").lower()


def test_wave_prime_override_mode(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(
        ce_host, "evolve_guard",
        lambda *_a, **_k: {"ok": True, "stdout": "snap"},
    )
    monkeypatch.setattr(
        "switchbay.ce_tools._ce_scan",
        lambda *_a, **_k: {"ok": True},
    )
    monkeypatch.setattr(
        "switchbay.ce_tools._ce_epoch_summary",
        lambda *_a, **_k: {"ok": True},
    )
    monkeypatch.setattr(
        "switchbay.ce_tools._ce_planner",
        lambda *_a, **_k: {"mode": "repair", "reason": "default"},
    )
    out = ce_host.wave_prime(tmp_path, {"mode": "tables"})
    assert out["mode"] == "multimodal-table-extract"
    assert "override" in out["reason"]


def test_ce_sweep_blurb_names_numeric_review():
    desc = tools.REGISTRY["ce_sweep"].description.lower()
    assert "pending-numeric-review" in desc
    assert "apply-numeric-review" in desc
    assert "multimodal-table-candidates" in desc
