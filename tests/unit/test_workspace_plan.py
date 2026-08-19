from switchbay import workspace_plan


def test_ensure_creates_three_files(tmp_path):
    root = workspace_plan.ensure(tmp_path)
    assert (root / "charter.md").is_file()
    assert (root / "work-plan.md").is_file()
    assert (root / "workspace-log.md").is_file()
    first = (root / "charter.md").read_text(encoding="utf-8")
    workspace_plan.ensure(tmp_path)
    assert (root / "charter.md").read_text(encoding="utf-8") == first


def test_append_log(tmp_path):
    workspace_plan.append_log(tmp_path, "Decided to try reviews-first.")
    text = (workspace_plan.plan_root(tmp_path) / "workspace-log.md").read_text(
        encoding="utf-8")
    assert "Decided to try reviews-first." in text
