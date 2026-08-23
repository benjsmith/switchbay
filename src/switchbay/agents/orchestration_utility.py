"""Slider → utility weights → candidate policies.

The Auto preference ``s ∈ [0, 1]`` (Economy → Maximum) sets cost and
latency weights. It does **not** select N. N is an observed output of
the highest-utility orchestration policy (and of later ΔU expansions).

Quantities are dimensionless relative to a cheapest-competent
single-agent baseline (C0 = L0 = 1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Preference: 0.0 Economy ← 0.5 Balanced → 1.0 Maximum
PREF_ECONOMY = 0.0
PREF_BALANCED = 0.5
PREF_MAXIMUM = 1.0

# λ(s) = floor + (max − floor) * (1 − s)². Floors stay strictly
# positive so Maximum still refuses zero-gain extra workers.
LAMBDA_C_MAX = 0.30
LAMBDA_C_FLOOR = 0.015
LAMBDA_L_MAX = 0.20
LAMBDA_L_FLOOR = 0.01

# Realized telemetry: cheapest-competent single-agent priors.
C0_TOKENS = 8_000.0
L0_SEC = 25.0

EXPANSION_THRESHOLD = 0.02
EPS = 1e-9

# Recipes. N is a *property* of a recipe, never the search variable.
RECIPES: dict[str, dict[str, Any]] = {
    "single": {
        "n": 1, "verify": False, "diverse": False,
        "ladder": "cheap", "execute": False,
        "why": "cheapest competent single agent",
    },
    "single_strong": {
        "n": 1, "verify": False, "diverse": False,
        "ladder": "strong", "execute": False,
        "why": "one stronger model",
    },
    "single_verify": {
        "n": 1, "verify": True, "diverse": False,
        "ladder": "balanced", "execute": False,
        "why": "one investigator plus a verifier",
    },
    "parallel_homog_2": {
        "n": 2, "verify": False, "diverse": False,
        "ladder": "balanced", "execute": False,
        "why": "two copies of the same model",
    },
    "parallel_diverse_2": {
        "n": 2, "verify": False, "diverse": True,
        "ladder": "balanced", "execute": False,
        "why": "two independent evidence paths",
    },
    "ivs_diverse_2": {
        "n": 2, "verify": True, "diverse": True,
        "ladder": "balanced", "execute": False,
        "why": "two independent investigators then verify",
    },
    "ivs_diverse_3": {
        "n": 3, "verify": True, "diverse": True,
        "ladder": "strong", "execute": False,
        "why": "three diverse investigators then verify",
    },
    "homog_4": {
        "n": 4, "verify": False, "diverse": False,
        "ladder": "balanced", "execute": False,
        "why": "four homogeneous investigators",
    },
    "ivs_homog_4": {
        "n": 4, "verify": True, "diverse": False,
        "ladder": "balanced", "execute": False,
        "why": "four same-model investigators then verify",
    },
    "swarm_8": {
        "n": 8, "verify": True, "diverse": False,
        "ladder": "strong", "execute": False,
        "why": "eight-way swarm (diminishing returns)",
    },
    "tools_verify": {
        "n": 2, "verify": True, "diverse": True,
        "ladder": "balanced", "execute": True,
        "why": "specialists plus deterministic execute and verify",
    },
}

# Nearby policies for conservative exploration. Never a swarm jump.
NEIGHBORS: dict[str, tuple[str, ...]] = {
    "single": ("single_strong", "single_verify"),
    "single_strong": ("single", "single_verify", "parallel_diverse_2"),
    "single_verify": ("single", "ivs_diverse_2"),
    "parallel_homog_2": ("single", "parallel_diverse_2", "ivs_diverse_2"),
    "parallel_diverse_2": ("parallel_homog_2", "ivs_diverse_2", "single_verify"),
    "ivs_diverse_2": ("single_verify", "ivs_diverse_3", "parallel_diverse_2"),
    "ivs_diverse_3": ("ivs_diverse_2", "ivs_homog_4"),
    "homog_4": ("ivs_diverse_2", "parallel_diverse_2"),
    "ivs_homog_4": ("ivs_diverse_2", "ivs_diverse_3"),
    "tools_verify": ("single_verify", "ivs_diverse_2"),
}


def clamp_preference(value: Any, default: float = PREF_BALANCED) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def cost_weight(preference: float) -> float:
    """λc(s): high at Economy, low but never zero at Maximum."""
    s = clamp_preference(preference)
    return LAMBDA_C_FLOOR + (LAMBDA_C_MAX - LAMBDA_C_FLOOR) * (1.0 - s) ** 2


def latency_weight(preference: float) -> float:
    """λl(s): same shape as cost. Floored so zero-gain work is refused."""
    s = clamp_preference(preference)
    return LAMBDA_L_FLOOR + (LAMBDA_L_MAX - LAMBDA_L_FLOOR) * (1.0 - s) ** 2


def utility(q: float, cnorm: float, lnorm: float, preference: float) -> float:
    """U(π, s) = Q − λc(s) Cnorm − λl(s) Lnorm."""
    return (
        float(q)
        - cost_weight(preference) * float(cnorm)
        - latency_weight(preference) * float(lnorm)
    )


def realized_utility(
    *,
    quality: float,
    cost_tokens: float,
    latency_s: float,
    preference: float,
) -> float:
    """Telemetry-time U using observed tokens/seconds vs C0/L0."""
    cnorm = float(cost_tokens) / max(C0_TOKENS, EPS)
    lnorm = float(latency_s) / max(L0_SEC, EPS)
    return utility(quality, cnorm, lnorm, preference)


def marginal_utility(
    dq: float, dc: float, dl: float, preference: float,
) -> float:
    return utility(dq, dc, dl, preference)


@dataclass
class CandidatePolicy:
    """One feasible orchestration topology. N is a field, not the key."""
    policy_id: str
    strategy: str
    n_investigators: int
    include_verify: bool
    include_reduce: bool
    include_execute: bool
    independence: str
    allow_expand: bool
    ladder_bias: str
    diversity: str
    q: float
    cnorm: float
    lnorm: float
    reason: str
    recipe: dict[str, Any] = field(default_factory=dict)

    def u(self, preference: float) -> float:
        return utility(self.q, self.cnorm, self.lnorm, preference)


def _clip01(x: float) -> float:
    return max(0.0, min(1.0, x))


def estimate_policy_quality(recipe: dict[str, Any], feat: Any) -> float:
    """Coarse prior Q ∈ [0, 1]. Ordering matters more than calibration."""
    n = int(recipe.get("n") or 1)
    verify = bool(recipe.get("verify"))
    diverse = bool(recipe.get("diverse"))
    ladder = str(recipe.get("ladder") or "balanced")
    execute = bool(recipe.get("execute"))
    research = bool(getattr(feat, "research", False))
    difficulty = float(getattr(feat, "difficulty", 0.2) or 0.0)
    consequence = float(getattr(feat, "consequence", 0.1) or 0.0)
    n_sub = int(getattr(feat, "n_subquestions", 1) or 1)
    finance = bool(getattr(feat, "finance", False))
    science = bool(getattr(feat, "science", False))
    experiment = bool(getattr(feat, "experiment", False))
    simple = difficulty < 0.3 and not research and n_sub <= 1
    prompt_len = int(getattr(feat, "prompt_len", 0) or 0)

    q = 0.70
    if simple:
        # Easy work: a stronger model barely helps.
        q = 0.78 if ladder != "cheap" else 0.76
    else:
        if ladder == "cheap":
            q -= 0.08
        elif ladder == "strong":
            q += 0.04
        if research:
            q -= 0.06
        if difficulty >= 0.55:
            q -= 0.06
        if n_sub >= 3:
            q -= 0.05
    # Unverified error is more expensive on consequential work.
    harm = 0.28 * consequence
    if verify:
        harm *= 0.15
        q += 0.04
        if consequence >= 0.45:
            q += 0.16 * consequence
        if research and prompt_len >= 80:
            q += 0.04
        if finance or science:
            q += 0.05
    q -= harm

    # Extra investigators: diversity changes ΔQ, not a mandate to grow N.
    extra_q = {2: 0.10, 3: 0.07, 4: 0.025, 5: 0.012, 6: 0.008, 7: 0.005, 8: 0.004}
    extra_h = {2: 0.03, 3: 0.018, 4: 0.01, 5: 0.006, 6: 0.004, 7: 0.003, 8: 0.002}
    for k in range(2, n + 1):
        add = (extra_q if diverse else extra_h).get(k, 0.002)
        if simple:
            add = min(add, 0.006)
        if n_sub >= k:
            add += 0.03
        q += add
    if execute and experiment:
        q += 0.16
    if simple and n > 1:
        q = min(q, 0.76 + 0.006 * (n - 1))
    return _clip01(q)


def estimate_policy_cost(recipe: dict[str, Any], feat: Any) -> float:
    """Cnorm relative to a cheap single agent. Parallel workers still add cost."""
    n = int(recipe.get("n") or 1)
    verify = bool(recipe.get("verify"))
    execute = bool(recipe.get("execute"))
    ladder = str(recipe.get("ladder") or "balanced")
    c = 1.0
    if ladder == "strong":
        c += 0.35
    elif ladder == "balanced" and n == 1:
        c += 0.15
    if n > 1:
        c += 0.75 * (n - 1)
    if verify:
        c += 0.45 if n == 1 else 0.65
    if execute:
        c += 0.50
    return max(0.05, c)


def estimate_policy_latency(recipe: dict[str, Any], feat: Any) -> float:
    """Lnorm on the DAG critical path — parallel workers ≈ max, not sum."""
    n = int(recipe.get("n") or 1)
    verify = bool(recipe.get("verify"))
    execute = bool(recipe.get("execute"))
    ladder = str(recipe.get("ladder") or "balanced")
    diverse = bool(recipe.get("diverse"))
    l = 1.0
    if ladder == "strong":
        l += 0.12
    if n > 1:
        l = max(l, 1.10 + (0.08 if diverse else 0.02))
    if execute:
        l = max(l, 1.18)
    if verify:
        l += 0.50 if n == 1 else 0.55
    return max(0.05, l)


def _independence(recipe: dict[str, Any], feat: Any) -> str:
    if recipe.get("diverse") or int(recipe.get("n") or 1) >= 2:
        if bool(getattr(feat, "research", False)) or bool(
            getattr(feat, "finance", False) or getattr(feat, "science", False)
        ):
            return "high"
    return str(getattr(feat, "independence", "") or "") or "medium"


def make_candidate(policy_id: str, feat: Any) -> CandidatePolicy | None:
    recipe = RECIPES.get(policy_id)
    if not recipe:
        return None
    n = int(recipe["n"])
    verify = bool(recipe["verify"])
    execute = bool(recipe["execute"])
    if n <= 1 and not verify and not execute:
        strategy = "single"
    elif verify:
        strategy = "investigate_verify_synthesize"
    else:
        strategy = "parallel_investigate"
    ladder = str(recipe["ladder"])
    diverse = bool(recipe["diverse"])
    ind = _independence(recipe, feat)
    if n <= 1 and not diverse:
        # Leave independence to the caller if it already estimated one.
        est = getattr(feat, "independence", None)
        if isinstance(est, str) and est:
            ind = est
        elif bool(getattr(feat, "research", False)) and float(
            getattr(feat, "difficulty", 0) or 0
        ) >= 0.45:
            ind = "high"
        elif float(getattr(feat, "difficulty", 0) or 0) < 0.3 and not getattr(
            feat, "research", False
        ):
            ind = "low"
        else:
            ind = "medium"
    q = estimate_policy_quality(recipe, feat)
    c = estimate_policy_cost(recipe, feat)
    l = estimate_policy_latency(recipe, feat)
    return CandidatePolicy(
        policy_id=policy_id,
        strategy=strategy,
        n_investigators=n,
        include_verify=verify,
        include_reduce=n >= 5,
        include_execute=execute and (
            bool(getattr(feat, "experiment", False))
            or bool(getattr(feat, "finance", False))
        ),
        independence=ind,
        allow_expand=bool(verify),
        ladder_bias=ladder,
        diversity="diverse" if diverse else "homogeneous",
        q=q, cnorm=c, lnorm=l,
        reason=str(recipe.get("why") or policy_id),
        recipe=dict(recipe),
    )


def generate_candidates(feat: Any) -> list[CandidatePolicy]:
    """3–6 sensible policies. Simple tasks stay near single-agent."""
    research = bool(getattr(feat, "research", False))
    difficulty = float(getattr(feat, "difficulty", 0.2) or 0.0)
    n_sub = int(getattr(feat, "n_subquestions", 1) or 1)
    finance = bool(getattr(feat, "finance", False))
    science = bool(getattr(feat, "science", False))
    experiment = bool(getattr(feat, "experiment", False))
    simple = (
        difficulty < 0.3 and not research and n_sub <= 1
        and not finance and not science
    )
    ids: list[str] = ["single", "single_strong"]
    if simple:
        ids.append("parallel_homog_2")
    else:
        if experiment:
            ids.append("tools_verify")
        ids.extend(["single_verify", "parallel_diverse_2", "ivs_diverse_2"])
        hard = difficulty >= 0.55 or finance or science or n_sub >= 3
        if hard:
            ids.append("ivs_diverse_3")
            ids.append("homog_4")
        else:
            ids.append("parallel_homog_2")
    # Bounded set; swarm_8 is test-only via make_candidate.
    seen: set[str] = set()
    out: list[CandidatePolicy] = []
    for pid in ids:
        if pid in seen:
            continue
        seen.add(pid)
        c = make_candidate(pid, feat)
        if c is not None:
            out.append(c)
        if len(out) >= 6:
            break
    return out


def choose_initial_candidate(
    feat: Any, *, preference: float | None = None,
) -> CandidatePolicy:
    s = clamp_preference(
        preference if preference is not None else getattr(feat, "preference", PREF_BALANCED)
    )
    cands = generate_candidates(feat)
    if not cands:
        c = make_candidate("single", feat)
        assert c is not None
        return c
    return max(cands, key=lambda c: c.u(s))


def estimate_marginal_quality(
    *,
    action: str,
    verification: dict[str, Any] | None,
    findings_n: int,
    consequence: float,
    unique_sources: int | None = None,
    nodes_so_far: int = 0,
) -> float:
    """Heuristic ΔQ for a proposed extra computation."""
    v = verification or {}
    conflicts = int(v.get("conflicts") or 0)
    unsupported = int(v.get("unsupported") or 0)
    unresolved = v.get("unresolved") or []
    n_unresolved = len(unresolved) if isinstance(unresolved, list) else 0
    try:
        conf = float(v.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    findings = max(1, int(findings_n or 1))
    gap = (
        conflicts > 0
        or (unsupported / findings >= 0.4)
        or n_unresolved > 0
        or conf < 0.4
    )
    if not gap:
        # No remaining uncertainty — extra computation is a copy.
        return 0.0 if action == "redundant_copy" else 0.008
    dq = 0.0
    if action in ("diverse_investigator", "investigator"):
        dq += 0.10 if action == "diverse_investigator" else 0.03
        if unique_sources is not None and nodes_so_far > 0:
            try:
                us = int(unique_sources)
            except (TypeError, ValueError):
                us = 0
            if us < max(1, nodes_so_far - 1):
                dq *= 0.4  # more of the same evidence
        if conflicts:
            dq += 0.08 * min(3, conflicts)
        if unsupported / findings >= 0.4:
            dq += 0.10
        if n_unresolved:
            dq += 0.06 * min(2, n_unresolved)
        if conf < 0.4:
            dq += 0.06
    elif action == "verifier":
        dq += 0.10
        if conflicts:
            dq += 0.10 * min(3, conflicts)
        if unsupported / findings >= 0.4:
            dq += 0.12
        if n_unresolved:
            dq += 0.05 * min(2, n_unresolved)
        dq += 0.14 * max(0.0, min(1.0, consequence))
        if conf < 0.4:
            dq += 0.08
    elif action == "redundant_copy":
        dq = 0.005
        if conflicts == 0 and unsupported == 0 and conf >= 0.8:
            dq = 0.0
    else:
        dq = 0.02
    return _clip01(dq)


def estimate_marginal_cost_latency(action: str) -> tuple[float, float]:
    """(ΔCnorm, ΔLnorm). Extra parallel workers are expensive in C, cheap in L.
    Expansion after verify sits on the critical path, so ΔL is real."""
    if action == "verifier":
        return 0.55, 0.50
    if action == "diverse_investigator":
        return 0.85, 0.70  # run then re-verify
    if action == "investigator":
        return 0.75, 0.65
    if action == "redundant_copy":
        return 0.75, 0.12  # parallel replica
    return 0.70, 0.50
