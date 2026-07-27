"""Propose → accept/reject write path (local-model curation)."""

from __future__ import annotations

from switchbay import proposals


def test_accept_writes_page(tmp_path):
    (tmp_path / "wiki").mkdir()
    e = proposals.add(
        tmp_path, op="create", kind="concept", title="Scaling Laws",
        body="# Scaling Laws\n\nBody text.",
    )
    assert e["status"] == "proposed"
    done = proposals.accept(tmp_path, e["id"])
    assert done is not None and done["status"] == "accepted"
    written = tmp_path / done["path"]
    assert written.is_file()
    assert "Scaling Laws" in written.read_text()


def test_dismiss_writes_nothing(tmp_path):
    (tmp_path / "wiki").mkdir()
    e = proposals.add(
        tmp_path, op="create", kind="concept", title="Ghost",
        body="nothing should be written",
    )
    done = proposals.dismiss(tmp_path, e["id"])
    assert done["status"] == "dismissed"
    # No file materialized for a dismissed proposal.
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


def test_accept_is_idempotent_once_resolved(tmp_path):
    (tmp_path / "wiki").mkdir()
    e = proposals.add(tmp_path, op="create", kind="note", title="N", body="x")
    proposals.accept(tmp_path, e["id"])
    # A second accept on an already-resolved proposal is a no-op (None).
    assert proposals.accept(tmp_path, e["id"]) is None
