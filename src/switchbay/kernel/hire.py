"""Hire / refuse. Slider prices quality vs cost; it never sets headcount.

The kernel thinks with the strongest *allowed* model, and only when a
hire is on the table. Worker models are a separate allocation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from math import sqrt
from pathlib import Path
from typing import Any

import re

from ..agents import orchestration_policy as policy
from .packages import (
    CODE_EDIT_ID, CODE_EXPLORE_ID, CODE_PLAN_ID, CODE_REVIEW_ID,
    CODING_FAMILY, PROJECT_COMMS_ID, PROJECT_PLAN_ID, PROJECT_REVIEW_ID,
    PROJECT_SENSE_ID, PROJECTS_FAMILY,
    WRITES_COMMS, WRITES_PLANS, WRITES_PRODUCT, WRITES_REVIEW, get_package,
)


@dataclass
class HireRequest:
    package_id: str
    justification: str
    needed_tools: list[str] = field(default_factory=list)
    needed_skills: list[str] = field(default_factory=list)
    kind: str = "specialist"  # specialist | clone | chief_upgrade
    evidence: str = ""
    desk_prior: bool = False  # Curate button already asked for this package


@dataclass
class HireDecision:
    accepted: bool
    reason: str
    provider: str | None = None
    model: str | None = None
    harness: str = "rail"
    ask_user: bool = False
    proposed_chief_provider: str | None = None
    proposed_chief_model: str | None = None
    package_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reason": self.reason,
            "provider": self.provider,
            "model": self.model,
            "harness": self.harness,
            "ask_user": self.ask_user,
            "proposed_chief_provider": self.proposed_chief_provider,
            "proposed_chief_model": self.proposed_chief_model,
            "package_id": self.package_id,
        }


def clone_marginal_value(n: int) -> float:
    """Relative value of the n-th same-kind copy (1/√n; first copy = 1)."""
    if n <= 1:
        return 1.0
    return 1.0 / sqrt(n)


def pick_kernel_model(
    *,
    workspace: Path | None,
    available: list[tuple[str, str | None]] | None = None,
    denied: list[str] | None = None,
) -> tuple[str, str | None] | None:
    """Strongest model marked available in the selection panel."""
    rows = policy.list_orchestrator_catalog(
        available=available, denied=denied, workspace=workspace,
    )
    allowed = [r for r in rows if r.get("allowed")]
    if not allowed:
        return None
    best = max(allowed, key=lambda r: float(r.get("strength") or 0))
    return str(best["provider"]), str(best.get("model") or "") or None


def pick_critic_model(
    *,
    workspace: Path | None,
    available: list[tuple[str, str | None]] | None = None,
    denied: list[str] | None = None,
) -> tuple[str, str | None] | None:
    """Strongest allowed model for verify/review. Independent of the slider.

    Authors stay on ``pick_worker_model``. Critique is a quality
    purchase even at Economy: the critic reads a compact artifact
    payload, not a transcript. If the rail chief already *is* that
    pair, we still seat it — the job is the model, not a different
    vendor.
    """
    return pick_kernel_model(
        workspace=workspace, available=available, denied=denied,
    )


CHECK_SKIP = "skip"
CHECK_CONFIRM = "confirm"
CHECK_REVISE = "revise"

_CLI_PROVIDERS = frozenset({
    "grok-build", "claude-code", "openai-codex", "muse-code",
})


def _provider_is_cli(pid: str) -> bool:
    if pid in _CLI_PROVIDERS:
        return True
    try:
        from .. import llmgateway
        return bool(llmgateway.can_execute(pid))
    except Exception:  # noqa: BLE001
        return False


def is_fast_class_model(model: str | None) -> bool:
    """Flash / luna / mini / haiku-class ids — fast synthesizers."""
    from .. import routing_status
    m = (model or "").strip()
    if not m:
        return False
    if routing_status.is_weak_model(m):
        return True
    token = m.lower()
    if "luna" in token:
        return True
    return policy.model_strength(m) <= 0.32


def pick_fast_model(
    *,
    workspace: Path | None,
    available: list[tuple[str, str | None]] | None = None,
    denied: list[str] | None = None,
) -> tuple[str, str | None] | None:
    """Fastest keyed HTTP model. Never a CLI agent loop.

    Prefers flash/luna/mini over flagship HTTP, and HTTP over local
    (cold-start). Returns None when only CLIs are allowed — caller
    should fall back to ordinary chat.
    """
    rows = policy.list_orchestrator_catalog(
        available=available, denied=denied, workspace=workspace,
    )
    allowed = [r for r in rows if r.get("allowed")]
    http = [r for r in allowed if not _provider_is_cli(str(r.get("provider") or ""))]
    if not http:
        return None

    def sort_key(r: dict[str, Any]) -> tuple[int, int, int, float]:
        model = str(r.get("model") or "")
        fast = is_fast_class_model(model)
        local = bool(r.get("local"))
        strength = float(r.get("strength") or 0)
        return (
            0 if (fast and not local) else 1,
            0 if fast else 1,
            0 if not local else 1,
            strength,
        )

    chosen = min(http, key=sort_key)
    model = str(chosen.get("model") or "") or None
    return str(chosen["provider"]), model


def strong_check_mode(
    preference: float,
    *,
    synth: tuple[str, str | None] | None,
    kernel: tuple[str, str | None] | None,
) -> str:
    """How involved the strongest model is on a fast lookup.

    Economy skips the check when a synthesizer already ran (flash/luna
    class is the intended synth; a second call would only add latency).
    Balanced asks for OK-or-rewrite. Maximum spends a few more tokens
    tightening the answer. Same-model kernel/synth is always skip.
    """
    s = policy.clamp_preference(preference)
    if not kernel or not synth or kernel == synth:
        return CHECK_SKIP
    if s < 0.35:
        return CHECK_SKIP
    if s < 0.8:
        return CHECK_CONFIRM
    return CHECK_REVISE


def pick_worker_model(
    *,
    preference: float,
    chief: tuple[str, str | None],
    workspace: Path | None,
    available: list[tuple[str, str | None]] | None = None,
    denied: list[str] | None = None,
) -> tuple[str, str | None]:
    """Worker allocation: Economy cheap/local, Maximum stronger — not the chief.

    Independence prefers a different pair from the rail picker when one exists.
    """
    s = policy.clamp_preference(preference)
    rows = policy.list_orchestrator_catalog(
        available=available, denied=denied, workspace=workspace,
    )
    allowed = [r for r in rows if r.get("allowed")]
    if not allowed:
        return chief
    chief_pid, chief_model = chief
    def pair(r: dict[str, Any]) -> tuple[str, str | None]:
        return str(r["provider"]), str(r.get("model") or "") or None

    others = [r for r in allowed if pair(r) != (chief_pid, chief_model)]
    pool = others or allowed
    if s <= 0.25:
        # Cheapest (local / flash / mini). Strength 0 is local.
        chosen = min(pool, key=lambda r: (
            0 if r.get("local") else 1,
            float(r.get("strength") or 0),
        ))
    elif s >= 0.8:
        # Strong but leave the very top for the kernel when possible.
        ranked = sorted(pool, key=lambda r: float(r.get("strength") or 0), reverse=True)
        chosen = ranked[1] if len(ranked) > 1 else ranked[0]
    else:
        ranked = sorted(pool, key=lambda r: float(r.get("strength") or 0))
        chosen = ranked[len(ranked) // 2]
    return pair(chosen)


def decide_hire(
    req: HireRequest,
    *,
    preference: float,
    chief: tuple[str, str | None],
    org: list[dict[str, Any]] | None = None,
    workspace: Path | None = None,
    available: list[tuple[str, str | None]] | None = None,
    denied: list[str] | None = None,
    chief_tools: list[str] | tuple[str, ...] | None = None,
    pi_available: bool = False,
) -> HireDecision:
    """Accept or refuse a specialist. Clones at Economy almost always die.

    Does not call a model; the caller may later ask the kernel model to
    interrogate a thin justification. Missing tools is already enough
    evidence. A Curate-desk prior accepts the curator package.
    """
    s = policy.clamp_preference(preference)
    pkg = get_package(req.package_id)
    org = list(org or [])
    same = [
        n for n in org
        if str(n.get("package") or n.get("package_id") or "") == req.package_id
    ]
    is_clone = req.kind == "clone" or bool(same)

    if req.kind == "chief_upgrade":
        return _chief_upgrade(
            preference=s, chief=chief, workspace=workspace,
            available=available, denied=denied, justification=req.justification,
        )

    if pkg is None:
        return HireDecision(
            False, f"unknown package {req.package_id!r}", package_id=req.package_id,
        )

    chief_set = set(chief_tools or [])
    missing = [t for t in (req.needed_tools or pkg.tools) if t not in chief_set]
    skills = list(req.needed_skills or pkg.needed_skills)
    has_gap = bool(missing) or bool(skills) or req.desk_prior

    if is_clone:
        n = len(same) + 1
        value = clone_marginal_value(n)
        # Hard cap: a third same-kind copy is never worth it.
        if n >= 3:
            return HireDecision(
                False,
                "refused clone: diminishing returns (same-kind workers)",
                package_id=req.package_id,
            )
        # 1/√n valuation: Economy (and most of the slider) refuses.
        if s * value < 0.5:
            return HireDecision(
                False,
                "refused clone: extra copy of the same specialist is not "
                f"worth the cost at this effort setting (1/√n n={n})",
                package_id=req.package_id,
            )

    if not has_gap and not req.justification.strip():
        return HireDecision(
            False,
            "refused: chief did not show missing tools/skills or a desk prior",
            package_id=req.package_id,
        )

    if pkg.writes == WRITES_REVIEW:
        critic = pick_critic_model(
            workspace=workspace, available=available, denied=denied,
        )
        worker = critic or pick_worker_model(
            preference=s, chief=chief, workspace=workspace,
            available=available, denied=denied,
        )
    else:
        worker = pick_worker_model(
            preference=s, chief=chief, workspace=workspace,
            available=available, denied=denied,
        )
    from .harness import pick_harness
    harness = pick_harness(pkg.id, worker[0], pi_available=pi_available)
    why = req.justification.strip() or (
        f"desk prior for {pkg.id}" if req.desk_prior
        else f"chief lacks tools: {', '.join(missing[:6])}"
    )
    return HireDecision(
        True,
        why,
        provider=worker[0],
        model=worker[1],
        harness=harness,
        package_id=pkg.id,
    )


# Job hints, not titles. Order is specificity (org/portfolio before
# generic plan/comms).
_PROJECTS_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ( "org-systems", re.compile(
        r"\b(bottleneck|feedback loop|communication network|local action "
        r"rules?|organisational systems?|organizational systems?|"
        r"many (innovation )?teams|system scale)\b", re.I,
    )),
    ( "portfolio-balance", re.compile(
        r"\b(portfolio|real options?|business case|project gates?|"
        r"resource (conflict|pool|contention)|risks? across|"
        r"balance (the )?(book|portfolio))\b", re.I,
    )),
    ( "project-review", re.compile(
        r"\b(scope drift|drift|review the plan|challenge the|"
        r"does (the|this) (plan|update|status) match)\b", re.I,
    )),
    ( "project-comms", re.compile(
        r"\b(tell the team|team (update|message)|exec(utive)? (deck|update|brief)|"
        r"community update|slides? for|standup|status update|"
        r"minimal messages?)\b", re.I,
    )),
    ( "project-plan", re.compile(
        r"\b(project plan|work-plan|targets?|metrics?|milestones?|"
        r"set (a )?gate|scope|charter)\b", re.I,
    )),
    ( "project-sense", re.compile(
        r"\b(what is going on|where are we|situation|cited situation|"
        r"ground(ing)? the)\b", re.I,
    )),
)

_CODING_HINTS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ( CODE_REVIEW_ID, re.compile(
        r"\b(review (the )?(diff|pr|patch|change)|code review)\b", re.I,
    )),
    ( CODE_EDIT_ID, re.compile(
        r"\b(implement|patch|fix the|write the (code|test)|refactor)\b", re.I,
    )),
    ( CODE_PLAN_ID, re.compile(
        r"\b(plan the (change|patch|fix)|design the (api|change))\b", re.I,
    )),
    ( CODE_EXPLORE_ID, re.compile(
        r"\b(where is|how does .* work|explore the (repo|code)|codebase)\b", re.I,
    )),
)

_WRITER = {WRITES_PLANS, WRITES_COMMS, WRITES_PRODUCT}
_CORE_PROJECTS: tuple[str, ...] = (
    PROJECT_SENSE_ID, PROJECT_PLAN_ID, PROJECT_COMMS_ID,
)
_CORE_CODING: tuple[str, ...] = (
    CODE_EXPLORE_ID, CODE_PLAN_ID, CODE_EDIT_ID,
)


def match_projects_packages(text: str) -> list[str]:
    """Ordered unique package ids hinted by the brief."""
    return _match_hints(text, _PROJECTS_HINTS)


def match_coding_packages(text: str) -> list[str]:
    return _match_hints(text, _CODING_HINTS)


def _match_hints(
    text: str, hints: tuple[tuple[str, re.Pattern[str]], ...],
) -> list[str]:
    blob = str(text or "")
    hit: list[str] = []
    for pid, pat in hints:
        if pat.search(blob) and pid not in hit:
            hit.append(pid)
    return hit


def _family_core(family: tuple[str, ...]) -> tuple[str, ...]:
    if family == PROJECTS_FAMILY:
        return _CORE_PROJECTS
    if family == CODING_FAMILY:
        return _CORE_CODING
    return ()


def _family_sense(family: tuple[str, ...]) -> str | None:
    if family == PROJECTS_FAMILY:
        return PROJECT_SENSE_ID
    if family == CODING_FAMILY:
        return CODE_EXPLORE_ID
    return None


def _family_review(family: tuple[str, ...]) -> str | None:
    if family == PROJECTS_FAMILY:
        return PROJECT_REVIEW_ID
    if family == CODING_FAMILY:
        return CODE_REVIEW_ID
    return None


def _has_writer(ids: list[str]) -> bool:
    for pid in ids:
        pkg = get_package(pid)
        if pkg is not None and pkg.writes in _WRITER:
            return True
    return False


def pick_family_hires(
    text: str,
    *,
    preference: float,
    chief: tuple[str, str | None],
    workspace: Path | None = None,
    available: list[tuple[str, str | None]] | None = None,
    denied: list[str] | None = None,
    chief_tools: list[str] | tuple[str, ...] | None = None,
    pi_available: bool = False,
    desk_prior: bool = True,
    family: tuple[str, ...] = PROJECTS_FAMILY,
    staff_desk: bool = False,
) -> list[HireDecision]:
    """Hire complementary packages. Economy does *not* cap at one kind:
    sense/plan/comms (or explore/plan/edit) are different write-authorities,
    so one hire cannot cover a desk. Worker models stay cheap at Economy.
    Clones of the same package still die.
    """
    s = policy.clamp_preference(preference)
    if family == PROJECTS_FAMILY:
        hinted = match_projects_packages(text)
    elif family == CODING_FAMILY:
        hinted = match_coding_packages(text)
    else:
        hinted = []
    sense = _family_sense(family)
    review = _family_review(family)
    core = [p for p in _family_core(family) if p in family]

    if staff_desk:
        # Authoritative: the slash canned prompt must not be parsed as
        # a narrow hint ("drift" in /work staff text used to hire only
        # project-review).
        want = list(core)
    elif hinted:
        want = list(hinted)
    elif desk_prior and sense and sense in family:
        want = [sense]
    else:
        return []

    if sense and sense in family and _has_writer(want) and sense not in want:
        want.insert(0, sense)
    # Review is its own permission surface. Economy still gets it (cheap
    # worker) when a writer is on the org — the critic must not hold the
    # writer's tools.
    if review and review in family and _has_writer(want) and review not in want:
        want.append(review)

    seen: set[str] = set()
    ordered: list[str] = []
    for pid in want:
        if pid in family and pid not in seen:
            seen.add(pid)
            ordered.append(pid)

    label = "work desk" if family == PROJECTS_FAMILY else "code desk"
    out: list[HireDecision] = []
    org: list[dict[str, Any]] = []
    for pid in ordered:
        d = decide_hire(
            HireRequest(
                package_id=pid,
                justification=f"{label}: {pid} (distinct write-authority)",
                desk_prior=desk_prior,
                kind="specialist",
            ),
            preference=s,
            chief=chief,
            org=org,
            workspace=workspace,
            available=available,
            denied=denied,
            chief_tools=chief_tools,
            pi_available=pi_available,
        )
        if d.accepted:
            out.append(d)
            org.append({"package": pid})
    return out


def _chief_upgrade(
    *,
    preference: float,
    chief: tuple[str, str | None],
    workspace: Path | None,
    available: list[tuple[str, str | None]] | None,
    denied: list[str] | None,
    justification: str,
) -> HireDecision:
    """Economy may ask the user to seat a stronger allowed chief. Never silent."""
    kernel_pair = pick_kernel_model(
        workspace=workspace, available=available, denied=denied,
    )
    if kernel_pair is None or kernel_pair == chief:
        return HireDecision(
            False, "no stronger allowed chief to propose", package_id="",
        )
    k_pid, k_model = kernel_pair
    rows = policy.list_orchestrator_catalog(
        available=available, denied=denied, workspace=workspace,
    )
    chief_s = 0.0
    new_s = 0.0
    for r in rows:
        pair = (str(r.get("provider")), str(r.get("model") or "") or None)
        if pair == chief:
            chief_s = float(r.get("strength") or 0)
        if pair == kernel_pair:
            new_s = float(r.get("strength") or 0)
    if new_s <= chief_s + 0.05:
        return HireDecision(
            False, "seated chief is already in the top band", package_id="",
        )
    return HireDecision(
        accepted=False,
        reason=justification or "kernel wants a stronger chief; ask the user",
        ask_user=True,
        proposed_chief_provider=k_pid,
        proposed_chief_model=k_model,
        package_id="",
    )
