"""Propose → accept/reject write path (local-model curation)."""

from __future__ import annotations

from switchbay import proposals


def test_scaffold_flag_and_clip(tmp_path):
    (tmp_path / "wiki").mkdir()
    huge = "# T\n\n" + ("claim\n" * 800)
    clipped = proposals.clip_scaffold_body(huge, title="T", cap=200)
    assert len(clipped) < len(huge)
    assert "truncated" in clipped.lower() or "Open questions" in clipped
    e = proposals.add(
        tmp_path, op="create", kind="note", title="Scaffolded",
        body="# Scaffolded\n\n- claim", scaffold=True,
    )
    assert e["scaffold"] is True


def test_accept_writes_page(tmp_path):
    (tmp_path / "wiki").mkdir()
    e = proposals.add(
        tmp_path, op="create", kind="concept", title="Scaling Laws",
        body="# Scaling Laws\n\nBody text.",
    )
    assert e["status"] == "proposed"
    # Provisional: the page is already on disk.
    assert (tmp_path / e["path"]).is_file()
    done = proposals.accept(tmp_path, e["id"])
    assert done is not None and done["status"] == "accepted"
    written = tmp_path / done["path"]
    assert written.is_file()
    assert "Scaling Laws" in written.read_text()


def test_dismiss_reverts_provisional_create(tmp_path):
    (tmp_path / "wiki").mkdir()
    e = proposals.add(
        tmp_path, op="create", kind="concept", title="Ghost",
        body="nothing should be written",
    )
    assert (tmp_path / e["path"]).is_file()
    done = proposals.dismiss(tmp_path, e["id"])
    assert done["status"] == "dismissed"
    assert not (tmp_path / e["path"]).exists()


def test_accept_refuses_unsafe_path(tmp_path):
    (tmp_path / "wiki").mkdir()
    e = proposals.add(
        tmp_path, op="edit", kind="concept", title="Escape",
        body="pwned", path="../../etc/evil.md",
    )
    done = proposals.accept(tmp_path, e["id"])
    # Path-traversal in an edit target is refused, not written.
    assert done["status"] == "dismissed"
    assert not (tmp_path.parent / "etc" / "evil.md").exists()


def test_dismiss_restores_edited_page(tmp_path):
    dest = tmp_path / "wiki" / "concepts" / "keep.md"
    dest.parent.mkdir(parents=True)
    dest.write_text("original\n", encoding="utf-8")
    e = proposals.add(
        tmp_path, op="edit", kind="concept", title="Keep",
        body="changed", path="wiki/concepts/keep.md",
    )
    assert dest.read_text(encoding="utf-8") == "changed\n"
    proposals.dismiss(tmp_path, e["id"])
    assert dest.read_text(encoding="utf-8") == "original\n"


def test_comments_rewrite_provisional_page(tmp_path):
    (tmp_path / "wiki").mkdir()
    e = proposals.add(
        tmp_path, op="create", kind="note", title="Draft",
        body="# Draft\n\nBody.",
    )
    dest = tmp_path / e["path"]
    proposals.apply_comments(tmp_path, e["id"], "tone down the claim")
    text = dest.read_text(encoding="utf-8")
    assert "tone down the claim" in text
    assert "Review comments" in text
    # A second save replaces the section, does not stack it.
    proposals.apply_comments(tmp_path, e["id"], "shorter")
    text = dest.read_text(encoding="utf-8")
    assert "shorter" in text
    assert text.count("Review comments") == 1
    assert "tone down the claim" not in text


def test_charter_proposal_reverts(tmp_path):
    from switchbay import workspace_plan
    workspace_plan.ensure(tmp_path)
    dest = workspace_plan.plan_root(tmp_path) / "charter.md"
    original = dest.read_text(encoding="utf-8")
    e = proposals.add(
        tmp_path, op="edit", kind="note", title="Charter",
        body="# Charter\n\nNew goals.\n",
        path=proposals.CHARTER_REL,
    )
    assert dest.read_text(encoding="utf-8").startswith("# Charter")
    proposals.dismiss(tmp_path, e["id"])
    assert dest.read_text(encoding="utf-8") == original


def test_accept_is_idempotent_once_resolved(tmp_path):
    (tmp_path / "wiki").mkdir()
    e = proposals.add(tmp_path, op="create", kind="note", title="N", body="x")
    proposals.accept(tmp_path, e["id"])
    # A second accept on an already-resolved proposal is a no-op (None).
    assert proposals.accept(tmp_path, e["id"]) is None
