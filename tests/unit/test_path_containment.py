"""Path-traversal containment on file-serving + data-destroying ops."""

from __future__ import annotations

from switchbay import daemon, splitting


def test_within_predicate(tmp_path):
    (tmp_path / "sub").mkdir()
    assert daemon._within(tmp_path, tmp_path / "sub" / "f.txt")
    assert daemon._within(tmp_path, tmp_path)                      # equal = inside
    assert not daemon._within(tmp_path, tmp_path.parent / "other")
    assert not daemon._within(tmp_path / "sub", tmp_path)          # parent not inside child


def test_safe_resolve_allows_in_tree(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "a.md").write_text("x")
    got = daemon._safe_resolve(tmp_path, "wiki/a.md")
    assert got == (tmp_path / "wiki" / "a.md").resolve()


def test_safe_resolve_blocks_dotdot(tmp_path):
    assert daemon._safe_resolve(tmp_path, "../../etc/passwd") is None


def test_safe_resolve_blocks_absolute_escape(tmp_path):
    assert daemon._safe_resolve(tmp_path, "/etc/passwd") is None


def test_safe_resolve_blocks_symlink_escape(tmp_path):
    outside = tmp_path.parent / "outside-secret"
    outside.mkdir(exist_ok=True)
    (outside / "s.txt").write_text("secret")
    link = tmp_path / "link"
    link.symlink_to(outside)
    # Resolving through the symlink escapes the workspace → refused.
    assert daemon._safe_resolve(tmp_path, "link/s.txt") is None


def test_validate_refs_flags_missing_and_traversal(tmp_path):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki" / "real.md").write_text("x")
    # real.md exists; ghost.md doesn't; a traversal ref resolves to a
    # non-file → all non-existent ones are returned as invalid, and the
    # split never touches them.
    invalid = splitting.validate_refs(tmp_path, ["real", "ghost", "../../../etc/hosts"])
    assert "real" not in invalid
    assert "ghost" in invalid
    assert "../../../etc/hosts" in invalid
