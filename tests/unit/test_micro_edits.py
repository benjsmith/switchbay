"""Unit tests for micro-edit classifier, policy, and ladder defaults."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from switchbay import micro_edits, modestore, sheet_focus


def test_is_micro_edit_needs_focus(tmp_path: Path):
    assert not micro_edits.is_micro_edit(tmp_path, "change the subtitle to foo")
    sheet_focus.save(tmp_path, {"a1": "H18", "used_range": "A1:H17"})
    assert micro_edits.is_micro_edit(tmp_path, "change the subtitle to foo")
    assert micro_edits.is_micro_edit(tmp_path, "put average formula in the selected cell")
    assert not micro_edits.is_micro_edit(
        tmp_path,
        "analyze the entire wiki and write a long report about architecture",
    )
    assert not micro_edits.is_micro_edit(tmp_path, "x" * 400)


def test_rung_precedence(tmp_path: Path):
    micro_edits.set_rung("global", tmp_path, None, "normal")
    assert micro_edits.effective_rung(tmp_path, "t1") == "normal"
    micro_edits.set_rung("workspace", tmp_path, None, "hard")
    assert micro_edits.effective_rung(tmp_path, "t1") == "hard"
    micro_edits.set_rung("thread", tmp_path, "t1", "trivial")
    assert micro_edits.effective_rung(tmp_path, "t1") == "trivial"
    assert micro_edits.effective_rung(tmp_path, "t2") == "hard"


def test_feedback_shown(tmp_path: Path):
    assert micro_edits.should_show_feedback(tmp_path, "t1")
    micro_edits.mark_feedback_shown("workspace", tmp_path, "t1")
    assert micro_edits.feedback_shown(tmp_path, "t1")
    assert not micro_edits.should_show_feedback(tmp_path, "t1")


def test_next_rung():
    assert micro_edits.next_rung("trivial") == "normal"
    assert micro_edits.next_rung("normal") == "hard"
    assert micro_edits.next_rung("hard") == "hard"


def test_ensure_ladder_defaults_is_noop():
    # 2026-07-24: seeding is gone (it created the confusing pinned-rung
    # state). The function returns the current ladder unchanged and
    # never writes.
    with patch("switchbay.modestore.global_ladder", return_value={"x": 1}) as gl:
        with patch("switchbay.modestore.set_global_ladder") as set_l:
            out = micro_edits.ensure_ladder_defaults("grok-build")
            assert out == {"x": 1}
            set_l.assert_not_called()
    assert gl.called


def test_micro_model_decoupled_from_ce_ladder(tmp_path: Path):
    (tmp_path / ".workbench").mkdir()
    # Unset → follow the picker (None), NOT the CE ladder.
    assert micro_edits.micro_model_for_rung(tmp_path, "trivial") == (None, None)
    # Set a workspace-scoped fast model at the trivial tier.
    micro_edits.set_micro_model("workspace", tmp_path, "trivial", "grok-build", "grok-4.5")
    assert micro_edits.micro_model_for_rung(tmp_path, "trivial") == ("grok-build", "grok-4.5")
    # A different tier stays unset (→ picker).
    assert micro_edits.micro_model_for_rung(tmp_path, "hard") == (None, None)
    # Clear → back to following the picker.
    micro_edits.clear_micro_models("workspace", tmp_path)
    assert micro_edits.micro_model_for_rung(tmp_path, "trivial") == (None, None)


def test_provider_without_model_follows_the_picker(tmp_path: Path):
    """A half-configured lane must not guess a model.

    Regression: a blank model used to fall through to the provider's
    `default_model`. On grok-build that resolved to `grok-4.5` — the
    flagship — for the lane whose whole purpose is to be cheap, and it
    routed somewhere other than what the picker displayed. Unset is
    unset at every level, and unset means the picker.
    """
    (tmp_path / ".workbench").mkdir()
    micro_edits.set_micro_model("workspace", tmp_path, "trivial", "grok-build", "")
    assert micro_edits.micro_model_for_rung(tmp_path, "trivial") == (None, None)
    assert micro_edits.resolve_micro_dispatch(tmp_path, None) is None


def test_dispatch_needs_both_provider_and_model(tmp_path: Path, monkeypatch):
    """A complete route dispatches; nothing else does."""
    (tmp_path / ".workbench").mkdir()

    class _Prov:
        PROVIDER = {"default_model": "grok-4.5"}

        @staticmethod
        def has_key():
            return True

    monkeypatch.setattr("switchbay.llmgateway.get", lambda pid: _Prov)
    micro_edits.set_micro_model(
        "workspace", tmp_path, "trivial", "grok-build", "grok-composer-2.5-fast")
    assert micro_edits.resolve_micro_dispatch(tmp_path, None) == (
        "grok-build", "grok-composer-2.5-fast", "trivial",
    )


def test_no_orphaned_provider_ladder_table():
    """The dead per-provider fast-model table stays deleted.

    It was defined but referenced nowhere, and reviving it would
    contradict "unset follows the picker".
    """
    assert not [n for n in dir(micro_edits) if "PROVIDER_LADDER" in n]


def test_parse_slash():
    assert micro_edits.parse_slash_args("")[0] == "status"
    act, payload = micro_edits.parse_slash_args("normal")
    assert act == "set" and payload == {"scope": "workspace", "rung": "normal"}
    act, payload = micro_edits.parse_slash_args("global hard")
    assert act == "set" and payload == {"scope": "global", "rung": "hard"}
    # New: clearing the micro-edit model → follow the picker.
    for word in ("picker", "off", "clear"):
        assert micro_edits.parse_slash_args(word)[0] == "clear"
