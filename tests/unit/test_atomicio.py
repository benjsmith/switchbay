"""Atomic-write helper: the durable-state safety net."""

from __future__ import annotations

import json

from switchbay import atomicio


def test_write_text_atomic_creates_and_overwrites(tmp_path):
    p = tmp_path / "reg.json"
    atomicio.write_text_atomic(p, "first\n")
    assert p.read_text() == "first\n"
    atomicio.write_text_atomic(p, "second\n")
    assert p.read_text() == "second\n"


def test_write_json_atomic_shape(tmp_path):
    p = tmp_path / "state.json"
    atomicio.write_json_atomic(p, {"paths": ["a", "b"], "active": "a"})
    # Trailing newline + pretty indent, matching the old write pattern.
    text = p.read_text()
    assert text.endswith("\n")
    assert json.loads(text) == {"paths": ["a", "b"], "active": "a"}


def test_no_temp_files_left_behind(tmp_path):
    p = tmp_path / "x.json"
    atomicio.write_json_atomic(p, {"k": 1})
    leftovers = [q.name for q in tmp_path.iterdir() if q.name != "x.json"]
    assert leftovers == []


def test_failure_leaves_no_partial_temp(tmp_path, monkeypatch):
    # If the write raises mid-way, the temp must be cleaned up and the
    # target left untouched (or absent) — never a half-written file.
    p = tmp_path / "y.json"
    p.write_text("original\n")

    class Boom(Exception):
        pass

    real_replace = atomicio.os.replace

    def explode(*_a, **_k):
        raise Boom("disk full")

    monkeypatch.setattr(atomicio.os, "replace", explode)
    try:
        atomicio.write_text_atomic(p, "new content")
    except Boom:
        pass
    monkeypatch.setattr(atomicio.os, "replace", real_replace)
    # Original intact; no stray temp file.
    assert p.read_text() == "original\n"
    leftovers = [q.name for q in tmp_path.iterdir() if q.name != "y.json"]
    assert leftovers == []
