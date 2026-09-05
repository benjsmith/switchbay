"""Kernel hire/refuse: slider prices quality, never N."""

from __future__ import annotations

from pathlib import Path

from switchbay.kernel import (
    HireRequest, decide_hire, pick_critic_model, pick_harness,
    pick_kernel_model, pick_worker_model,
)
from switchbay.kernel.packages import CURATOR_ID, CURATOR_TOOLS, RESEARCH_ID


def _avail() -> list[tuple[str, str | None]]:
    return [
        ("anthropic", "claude-opus-4"),
        ("gemini", "gemini-3.8-flash"),
        ("mlx", "qwen2.5-7b"),
        ("grok-build", "grok-4.6"),
    ]


def test_economy_refuses_clone(tmp_path: Path):
    chief = ("anthropic", "claude-opus-4")
    d = decide_hire(
        HireRequest(package_id=CURATOR_ID, justification="another curator", kind="clone"),
        preference=0.0,
        chief=chief,
        org=[{"package": CURATOR_ID, "provider": "gemini", "model": "flash"}],
        workspace=tmp_path,
        available=_avail(),
        denied=[],
    )
    assert d.accepted is False
    assert "clone" in d.reason


def test_curate_desk_prior_hires_specialist(tmp_path: Path):
    d = decide_hire(
        HireRequest(
            package_id=CURATOR_ID,
            justification="curate desk",
            needed_tools=list(CURATOR_TOOLS),
            desk_prior=True,
        ),
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        org=[],
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki", "read_wiki_page"],
        pi_available=False,
    )
    assert d.accepted is True
    assert d.package_id == CURATOR_ID
    # Economy worker should not be the flagship chief.
    assert (d.provider, d.model) != ("anthropic", "claude-opus-4")


def test_missing_justification_refused(tmp_path: Path):
    d = decide_hire(
        HireRequest(package_id=CURATOR_ID, justification=""),
        preference=0.5,
        chief=("anthropic", "claude-opus-4"),
        org=[],
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=list(CURATOR_TOOLS),
    )
    assert d.accepted is False


def test_clone_value_is_one_over_sqrt_n():
    from switchbay.kernel.hire import clone_marginal_value
    assert clone_marginal_value(1) == 1.0
    assert abs(clone_marginal_value(2) - 0.7071) < 0.01
    assert abs(clone_marginal_value(4) - 0.5) < 1e-9


def test_maximum_can_still_refuse_third_clone(tmp_path: Path):
    d = decide_hire(
        HireRequest(package_id=CURATOR_ID, justification="more", kind="clone"),
        preference=1.0,
        chief=("anthropic", "claude-opus-4"),
        org=[
            {"package": CURATOR_ID},
            {"package": CURATOR_ID},
        ],
        workspace=tmp_path,
        available=_avail(),
        denied=[],
    )
    assert d.accepted is False
    assert "diminishing" in d.reason


def test_kernel_model_is_strongest_allowed(tmp_path: Path):
    pair = pick_kernel_model(workspace=tmp_path, available=_avail(), denied=[])
    assert pair is not None
    assert pair[0] in {"anthropic", "grok-build"}


def test_chief_upgrade_asks_user(tmp_path: Path):
    d = decide_hire(
        HireRequest(package_id="", justification="too weak", kind="chief_upgrade"),
        preference=0.0,
        chief=("mlx", "qwen2.5-7b"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
    )
    assert d.accepted is False
    assert d.ask_user is True
    assert d.proposed_chief_provider in {"anthropic", "grok-build"}


def test_denied_model_is_not_proposed(tmp_path: Path):
    d = decide_hire(
        HireRequest(package_id="", justification="upgrade", kind="chief_upgrade"),
        preference=0.0,
        chief=("mlx", "qwen2.5-7b"),
        workspace=tmp_path,
        available=_avail(),
        denied=["anthropic", "grok-build"],
    )
    # Flash is allowed and stronger than 7b.
    if d.ask_user:
        assert d.proposed_chief_provider == "gemini"


def test_critic_is_kernel_model(tmp_path: Path):
    pair = pick_critic_model(workspace=tmp_path, available=_avail(), denied=[])
    kernel = pick_kernel_model(workspace=tmp_path, available=_avail(), denied=[])
    assert pair == kernel
    assert pair is not None
    assert pair[0] in {"anthropic", "grok-build"}


def test_review_hires_strongest_even_at_economy(tmp_path: Path):
    from switchbay.kernel.packages import CODE_REVIEW_ID
    d = decide_hire(
        HireRequest(
            package_id=CODE_REVIEW_ID,
            justification="review the diff",
            desk_prior=True,
        ),
        preference=0.0,
        chief=("gemini", "gemini-3.8-flash"),
        org=[],
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki"],
        pi_available=False,
    )
    assert d.accepted is True
    assert (d.provider, d.model) == ("anthropic", "claude-opus-4")


def test_pick_harness_grok_not_pi():
    assert pick_harness(CURATOR_ID, "grok-build", pi_available=True) == "grok-build"


def test_pick_harness_pi_for_curator_when_present():
    assert pick_harness(CURATOR_ID, "anthropic", pi_available=True) == "pi"
    assert pick_harness(CURATOR_ID, "anthropic", pi_available=False) == "rail"


def test_pick_harness_copilot_is_not_pi():
    assert pick_harness(CURATOR_ID, "github_copilot", pi_available=True) == "rail"
    assert pick_harness(CURATOR_ID, "unknown-vendor", pi_available=True) == "rail"


def test_research_desk_prior_hires(tmp_path: Path):
    d = decide_hire(
        HireRequest(
            package_id=RESEARCH_ID,
            justification="research desk",
            needed_tools=["research_search", "research_fetch"],
            desk_prior=True,
        ),
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        org=[],
        workspace=tmp_path,
        available=_avail(),
        denied=[],
        chief_tools=["search_wiki"],
        pi_available=False,
    )
    assert d.accepted is True
    assert d.package_id == RESEARCH_ID


def test_worker_economy_prefers_cheap(tmp_path: Path):
    worker = pick_worker_model(
        preference=0.0,
        chief=("anthropic", "claude-opus-4"),
        workspace=tmp_path,
        available=_avail(),
        denied=[],
    )
    assert worker[0] in {"mlx", "gemini"}
