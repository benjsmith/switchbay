"""Auto orchestration policy, cost/performance preference, telemetry.

Hand-authored priors first; a small inspectable contextual bandit
nudges nearby recipe choices over time, **per workspace** and coarse
task-type bucket. Never required to run: missing, corrupt, or
version-mismatched state falls back to the priors.

The learner may not change hard resource/security bounds. Other
vaults do not share this file. Provider roster memory lives on the
desk playbook (``.orchestrator/state/playbook.json``), also per
workspace.
"""

from __future__ import annotations

import json
import logging
import math
import os
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .. import atomicio, statedir
from . import orchestration_utility as util

log = logging.getLogger("switchbay.agents.orchestration_policy")

POLICY_VERSION = 2

# Preference: 0.0 Economy ← 0.5 Balanced → 1.0 Maximum
PREF_ECONOMY = 0.0
PREF_BALANCED = 0.5
PREF_MAXIMUM = 1.0

STRATEGIES = (
    "single",
    "fast_lookup",
    "parallel_investigate",
    "investigate_verify_synthesize",
)

# Hard bounds — the slider and the learner operate *inside* these.
# Learning must never raise them.
#
# Parent lifetime is *not* a wall clock. The chief-of-staff Run stays
# alive until OBJECTIVE_MET, ΔU ≤ 0 (idle), user kill, or every
# usable channel is in cooldown (then it waits and auto-resumes).
# 0 = no parent cap. Child workers still have HARD_WORKER_TIMEOUT_SEC.
#
# Spawned-worker lifetime caps are 0 (unlimited). ΔU and the stop
# token are the brake; a ballooning DAG is a formula bug, not a
# reason to clip the desk. HARD_MAX_CONCURRENCY is parallel slots
# on this machine, not a lifetime N.
HARD_MAX_NODES = 0
HARD_MAX_DEPTH = 64
HARD_MAX_CONCURRENCY = 8
HARD_MAX_EXPANSIONS = 0
HARD_MAX_CONTINUATIONS = 0
HARD_WALL_CLOCK_SEC = 0.0
# Per-child cap. A grok-build investigator doing real retrieval
# routinely exceeds 3 minutes; the old 180s wait_for killed those
# and surfaced "node cancelled" on the rail while the CLI kept running.
HARD_WORKER_TIMEOUT_SEC = 900.0

# Provider categories used when overnight Auto has exhausted
# subscriptions and wants to ask before burning BYOK credits.
LOCAL_PROVIDER_IDS = frozenset({"mlx", "llamacpp", "ollama"})
SUBSCRIPTION_CATEGORIES = frozenset({"subscription"})
BYOK_CATEGORIES = frozenset({"byok"})

_RESEARCH_RE = re.compile(
    r"\b(research|investigat\w*|evidence|compar(e|ison)|analy[sz]|"
    r"why\b|conflict|forecast|uncertain|debate|verif\w*|source|"
    r"contradict|ambiguous|adversarial|"
    r"vs\.?|versus|trade-?offs?)\b",
    re.I,
)
# Wiki + open web + vault write is a research desk, not a chat turn.
_WEB_INGEST_RE = re.compile(
    r"\b("
    r"open web|web search|search the web|the internet|"
    r"fetch (a |one |the )?(url|paper|pdf|source)|"
    r"into the vault|add to (the )?vault|ingest"
    r")\b",
    re.I,
)
_CODE_RE = re.compile(
    r"\b(code|bug|test|implement|refactor|function|compile|traceback|"
    r"stack\s*trace|lint|type.?error)\b",
    re.I,
)
_GRAPH_RE = re.compile(
    r"\b(wiki|graph|vault|knowledge|what do (we|i) know|wikilink|"
    r"neighbors?|page)\b",
    re.I,
)
# Factual / "what's in the wiki" questions that a retrieve+synth
# pass can answer without seating a DAG.
_LOOKUP_RE = re.compile(
    r"\b("
    r"what (is|are|do|does|did|was|were)|"
    r"who (is|are|was|were)|"
    r"when (did|was|is|were)|"
    r"where (is|are|was)|"
    r"how (does|do|did|is|are)|"
    r"explain|define|tell me about"
    r")\b",
    re.I,
)
_LOW_IND_RE = re.compile(
    r"\b(summar(y|ise|ize)|format|rewrite|rephrase|translate|"
    r"bullet|list the|title this|shorten|plain text)\b",
    re.I,
)
_CONSEQ_RE = re.compile(
    r"\b(decision|consequential|legal|medical|safety|irreversible|"
    r"important|high.?stakes|must be (sure|correct|right))\b",
    re.I,
)
_FINANCE_RE = re.compile(
    r"\b(filings?|10-?k|10-?q|8-?k|13f|form 4|earnings|eps|ticker|"
    r"watchlist|alpha|quant|hedge fund|insider|13d|transcript|"
    r"consensus|sector rotation|short interest)\b",
    re.I,
)
_SCIENCE_RE = re.compile(
    r"\b(experiment|hypothesis|lab(oratory)?|assay|protocol|replicate|"
    r"measurement|spectrometer|p-?value|wet lab|autonomous experiment|"
    r"instrument|calibration|control group|ablation)\b",
    re.I,
)
_EXPERIMENT_RE = re.compile(
    r"\b(run the (experiment|protocol|assay)|execute (the )?(protocol|run)|"
    r"measure|instrument|lab (system|rig|device)|autonomous experiment)\b",
    re.I,
)
_MULTI_RE = re.compile(
    r"(?:\?|^\s*\d+[\.\)]\s|^\s*[-*]\s|\band also\b|\bfurthermore\b)",
    re.I | re.M,
)


@dataclass
class TaskFeatures:
    prompt_len: int = 0
    research: bool = False
    graph: bool = False
    code: bool = False
    n_subquestions: int = 1
    difficulty: float = 0.2
    consequence: float = 0.1
    provider_diversity: int = 1
    preference: float = PREF_BALANCED
    finance: bool = False
    science: bool = False
    experiment: bool = False
    lookup: bool = False

    def bucket(self) -> str:
        """Coarse, stable context key for the bandit."""
        length = "s" if self.prompt_len < 120 else ("m" if self.prompt_len < 600 else "l")
        kind = (
            "f" if self.finance else (
                "e" if self.science else (
                    "r" if self.research else (
                        "c" if self.code else ("g" if self.graph else "n")
                    )
                )
            )
        )
        diff = "h" if self.difficulty >= 0.6 else ("m" if self.difficulty >= 0.3 else "l")
        cons = "c" if self.consequence >= 0.5 else "o"
        pref = int(round(self.preference * 4))  # 0..4
        sub = "m" if self.n_subquestions >= 3 else "1"
        div = "d" if self.provider_diversity >= 2 else "s"
        return f"{kind}|{length}|{diff}|{cons}|p{pref}|{sub}|{div}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, raw: Any) -> TaskFeatures:
        if not isinstance(raw, dict):
            return cls()
        out = cls()
        for k in out.__dataclass_fields__:
            if k in raw:
                setattr(out, k, raw[k])
        try:
            out.preference = max(0.0, min(1.0, float(out.preference)))
        except (TypeError, ValueError):
            out.preference = PREF_BALANCED
        return out


@dataclass
class PolicyDecision:
    strategy: str
    n_investigators: int
    include_verify: bool
    include_reduce: bool
    independence: str
    allow_expand: bool
    ladder_bias: str
    reason: str
    include_execute: bool = False
    explored: bool = False
    arm_id: str = "single"
    features: dict[str, Any] = field(default_factory=dict)
    preference: float = PREF_BALANCED

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def clamp_preference(value: Any, default: float = PREF_BALANCED) -> float:
    return util.clamp_preference(value, default)


def cost_weight(preference: float) -> float:
    """λc(s): high at Economy, low but never zero at Maximum."""
    return util.cost_weight(preference)


def latency_weight(preference: float) -> float:
    """λl(s): same shape as cost. Floored so zero-gain work is refused."""
    return util.latency_weight(preference)


def extract_features(
    text: str,
    *,
    preference: float = PREF_BALANCED,
    provider_diversity: int = 1,
    graph_available: bool = True,
) -> TaskFeatures:
    t = text or ""
    n_q = len(re.findall(r"\?", t))
    n_list = len(_MULTI_RE.findall(t))
    n_sub = max(1, n_q + max(0, n_list // 2))
    research = bool(_RESEARCH_RE.search(t) or _WEB_INGEST_RE.search(t))
    code = bool(_CODE_RE.search(t))
    graph = bool(_GRAPH_RE.search(t)) if graph_available else False
    finance = bool(_FINANCE_RE.search(t))
    science = bool(_SCIENCE_RE.search(t))
    experiment = bool(_EXPERIMENT_RE.search(t)) or (
        science and bool(re.search(r"\b(run|execute|measure)\b", t, re.I))
    )
    low = bool(_LOW_IND_RE.search(t))
    lookup = bool(_LOOKUP_RE.search(t) or graph)
    if low and not graph:
        # Rewrites / summaries of pasted text are not wiki lookups.
        lookup = False
    cons = 0.55 if _CONSEQ_RE.search(t) else (
        0.5 if finance or science else (0.35 if research else 0.1)
    )
    length = len(t.strip())
    difficulty = 0.15
    if length > 400:
        difficulty += 0.2
    if length > 1200:
        difficulty += 0.15
    if research or finance or science:
        difficulty += 0.25
    if n_sub >= 3:
        difficulty += 0.15
    if code or experiment:
        difficulty += 0.1
    if low and not finance and not science:
        difficulty = min(difficulty, 0.25)
    return TaskFeatures(
        prompt_len=length,
        research=research or finance or science,
        graph=graph,
        code=code,
        n_subquestions=min(8, n_sub),
        difficulty=max(0.0, min(1.0, difficulty)),
        consequence=max(0.0, min(1.0, cons)),
        provider_diversity=max(1, int(provider_diversity)),
        preference=clamp_preference(preference),
        finance=finance,
        science=science,
        experiment=experiment,
        lookup=lookup,
    )


def apply_task_context(
    features: TaskFeatures,
    *,
    task_kind: str | None = None,
    constrained: bool = False,
) -> TaskFeatures:
    """Apply product-known context that terse canned prompts cannot express.

    Wiki CURATE is one CE orchestrator (planner pick-mode + Phase 2),
    not Switch Bay investigators. Local/focused passes stay conservative.
    """
    if task_kind == "curation":
        features.graph = True
        features.lookup = False
        if not constrained:
            features.n_subquestions = 1
    if task_kind in {"projects", "code", "deck"}:
        features.graph = True
        features.lookup = False
        if not constrained:
            features.n_subquestions = max(features.n_subquestions, 1)
    return features


def is_fast_lookup_task(features: TaskFeatures) -> bool:
    """Wiki/factual questions that retrieve+fast-synth can answer.

    Research, code, finance, science, and multi-part work stay on the
    DAG. Rewrite/summarize prompts are not lookups unless they also
    name the wiki.
    """
    if (
        features.research or features.finance or features.science
        or features.experiment or features.code
    ):
        return False
    if features.n_subquestions > 1 or features.difficulty >= 0.3:
        return False
    return bool(features.lookup)


def estimate_independence(features: TaskFeatures) -> str:
    if features.finance or features.science or features.consequence >= 0.5 or (
        features.research and features.difficulty >= 0.45
    ):
        return "high"
    text_low = features.difficulty < 0.3 and not features.research and features.n_subquestions <= 1
    if text_low:
        return "low"
    return "medium"


def _candidate_to_decision(
    cand: util.CandidatePolicy, features: TaskFeatures, *, reason: str | None = None,
) -> PolicyDecision:
    independence = cand.independence
    if independence not in ("low", "medium", "high"):
        independence = estimate_independence(features)
    return PolicyDecision(
        strategy=cand.strategy,
        n_investigators=cand.n_investigators,
        include_verify=cand.include_verify,
        include_reduce=cand.include_reduce,
        include_execute=cand.include_execute,
        independence=independence,
        allow_expand=cand.allow_expand,
        ladder_bias=cand.ladder_bias,
        reason=reason or cand.reason,
        arm_id=cand.policy_id,
        features=features.to_dict(),
        preference=features.preference,
    )


def choose_initial_policy(features: TaskFeatures) -> PolicyDecision:
    """argmax_π U(π, s). N is a property of π, not the decision variable."""
    cand = util.choose_initial_candidate(features, preference=features.preference)
    return _candidate_to_decision(cand, features)


def _prior_decision(features: TaskFeatures) -> PolicyDecision:
    """Priors = utility-maximising candidate. Kept as the decide() baseline."""
    return choose_initial_policy(features)


def _arm_neighbors(arm_id: str) -> list[str]:
    """Small policy perturbations — never N±1 as the search."""
    return list(util.NEIGHBORS.get(arm_id, ("single",)))


def _decision_from_arm(
    arm_id: str, features: TaskFeatures, base: PolicyDecision,
) -> PolicyDecision:
    cand = util.make_candidate(arm_id, features)
    if cand is None:
        return base
    d = _candidate_to_decision(cand, features, reason=base.reason)
    if arm_id == "single" and base.explored:
        d.reason = base.reason + "; explored single"
    return d


def _epsilon(features: TaskFeatures, state: dict[str, Any] | None = None) -> float:
    s = features.preference
    # Explore a little more on cheap/non-consequential work; less on
    # expensive or high-stakes tasks. Never high enough to feel random.
    # Never zero: lock-in is a degenerate loop.
    base = 0.04 + 0.08 * s
    if features.consequence >= 0.5:
        base *= 0.35
    if features.prompt_len < 80 and s < 0.4:
        base *= 1.4
    if isinstance(state, dict):
        bucket = ((state.get("buckets") or {}).get(features.bucket()) or {})
        arms = bucket.get("arms") or {}
        n = sum(int(a.get("n") or 0) for a in arms.values() if isinstance(a, dict))
        if n >= 8:
            base *= 0.5
        if n >= 20:
            base *= 0.5
    return max(0.01, min(0.12, base))


def decide(
    features: TaskFeatures,
    *,
    state: dict[str, Any] | None = None,
    rng: random.Random | None = None,
) -> PolicyDecision:
    """Pick a policy. Priors always work; telemetry only nudges."""
    prior = choose_initial_policy(features)
    st = state if isinstance(state, dict) and state.get("version") == POLICY_VERSION else None
    if st is None:
        return prior
    rng = rng or random.Random()
    bucket = features.bucket()
    arms = ((st.get("buckets") or {}).get(bucket) or {}).get("arms") or {}
    valid = {c.policy_id for c in util.generate_candidates(features)}
    valid.add(prior.arm_id)
    # Exploit: best-known *policy* in this bucket, else prior.
    # Score is mean realized utility. Do not reward bigger N.
    best_arm = prior.arm_id
    best_score = None
    for arm, stats in arms.items():
        if not isinstance(stats, dict) or arm not in valid:
            continue
        n = int(stats.get("n") or 0)
        if n < 2:
            continue
        mean = float(stats.get("sum_reward") or 0.0) / n
        qpn = float(stats.get("sum_quality_per_node") or 0.0) / n
        score = mean + 0.1 * qpn
        if best_score is None or score > best_score:
            best_score = score
            best_arm = arm
    chosen = _decision_from_arm(best_arm, features, prior)
    chosen.reason = prior.reason if best_arm == prior.arm_id else (
        f"learned {best_arm} for similar tasks; {prior.reason}"
    )
    # Do not explore extra computation on easy work.
    if (
        chosen.arm_id in ("single", "fast_lookup")
        and features.difficulty < 0.4
        and not features.research
    ):
        return chosen
    if rng.random() < _epsilon(features, st):
        neighbors = [
            a for a in _arm_neighbors(chosen.arm_id)
            if _arm_within_candidates(a, valid)
        ]
        if neighbors:
            alt = rng.choice(neighbors)
            explored = _decision_from_arm(alt, features, chosen)
            explored.explored = True
            explored.reason = f"explore {alt} (near {chosen.arm_id}); {chosen.reason}"
            return explored
    return chosen


def _arm_within_candidates(arm_id: str, valid: set[str]) -> bool:
    """Exploration stays inside the task's candidate set, not an N cap."""
    if arm_id == "single":
        return True
    if arm_id == "swarm_8":
        return False
    return arm_id in valid or arm_id in util.RECIPES


# ── diversity ──────────────────────────────────────────────────────


def list_keyed_providers(*, scan_local_disk: bool = True) -> list[tuple[str, str]]:
    """(provider_id, default_model) that currently have a key.

    Admin policy already filters ``list_providers()``, so enterprise
    installs only see Copilot + local.

    ``scan_local_disk=False`` skips Hugging Face cache walks (MLX /
    llama.cpp ``has_key``). Use that on the dashboard catalog path.
    """
    from .. import admin_policy, llm_config, llmgateway
    out: list[tuple[str, str]] = []
    for pid, prov in llmgateway.PROVIDERS.items():
        if not admin_policy.provider_allowed(pid):
            continue
        if scan_local_disk:
            try:
                keyed = bool(prov.has_key())
            except Exception:  # noqa: BLE001
                keyed = False
        else:
            keyed = _provider_is_keyed_cheap(pid)
        if not keyed:
            continue
        model = str(
            llm_config.get_model(pid)
            or prov.PROVIDER.get("chosen_model")
            or prov.PROVIDER.get("default_model")
            or "",
        )
        out.append((pid, model))
    return out


def _provider_is_keyed_cheap(pid: str) -> bool:
    """has_key without walking the Hugging Face cache.

    Local backends otherwise call ``list_installed()`` → ``iterdir`` on
    every HF snapshot, which blocked the dashboard catalog for a minute.
    """
    from .. import localllm, llmgateway, model_cache
    try:
        prov = llmgateway.get(pid)
    except Exception:  # noqa: BLE001
        return False
    if pid not in LOCAL_PROVIDER_IDS:
        try:
            return bool(prov.has_key())
        except Exception:  # noqa: BLE001
            return False
    cfg = localllm.load_config() or {}
    if str(cfg.get("backend") or "") == pid:
        return True
    cached, _fresh = model_cache.get_cached(pid)
    if cached:
        return True
    if pid == "mlx":
        fn = getattr(prov, "supported", None)
        try:
            return bool(fn()) if callable(fn) else False
        except Exception:  # noqa: BLE001
            return False
    if pid == "ollama":
        try:
            return bool(prov.has_key())
        except Exception:  # noqa: BLE001
            return False
    return False


def provider_category(provider_id: str) -> str:
    """subscription / byok / local / ''."""
    if not provider_id:
        return ""
    if provider_id in LOCAL_PROVIDER_IDS:
        return "local"
    from .. import llmgateway
    try:
        prov = llmgateway.get(provider_id)
    except Exception:  # noqa: BLE001
        return ""
    return str((getattr(prov, "PROVIDER", None) or {}).get("category") or "")


def filter_keyed_providers(
    pairs: list[tuple[str, str]] | None = None,
    *,
    include_byok: bool = True,
    include_local: bool = True,
    always: str | None = None,
) -> list[tuple[str, str]]:
    """Subset of keyed providers for overnight channel selection."""
    src = pairs if pairs is not None else list_keyed_providers()
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    for pid, model in src:
        cat = provider_category(pid)
        if pid == always:
            pass
        elif cat == "byok" and not include_byok:
            continue
        elif cat == "local" and not include_local:
            continue
        if pid in seen:
            continue
        seen.add(pid)
        out.append((pid, model))
    if always and always not in seen:
        out.insert(0, (always, ""))
    return out


def model_family(model: str | None) -> str:
    """Coarse family for intra-provider diversity (Copilot GPT vs Claude vs Gemini)."""
    m = (model or "").strip().lower()
    if not m:
        return ""
    vendor, _, rest = m.partition("/")
    token = rest or vendor
    if any(s in token for s in ("claude", "sonnet", "opus", "haiku", "anthropic")):
        return "claude"
    if token.startswith(("o1", "o3", "o4")) or any(
        s in token for s in ("o1-", "o3-", "o4-", "codex-mini")
    ):
        return "o-series"
    if "gpt" in token or token.startswith("openai"):
        return "gpt"
    if "gemini" in token or "gemma" in token:
        return "gemini"
    if "grok" in token:
        return "grok"
    if "llama" in token or token.startswith("meta"):
        return "llama"
    if "mistral" in token or "mixtral" in token or "codestral" in token:
        return "mistral"
    if "qwen" in token:
        return "qwen"
    if "deepseek" in token:
        return "deepseek"
    if token.startswith("phi") or "phi-" in token:
        return "phi"
    if "/" in m:
        return vendor
    return token.split("-", 1)[0] or token


def models_for_provider(pid: str) -> list[str]:
    """Chat models this provider can actually route to.

    Prefers the live/cached catalog (Copilot ``GET /models``, Ollama
    tags, …) and falls back to static suggestions. Empty if admin
    policy hides the provider.
    """
    from .. import admin_policy, llmgateway, model_cache
    if not pid or not admin_policy.provider_allowed(pid):
        return []
    cached, _fresh = model_cache.get_cached(pid)
    models = [str(m) for m in cached if m]
    if not models:
        try:
            prov = llmgateway.get(pid)
        except llmgateway.ProviderError:
            return []
        models = [str(m) for m in (prov.PROVIDER.get("model_suggestions") or []) if m]
    # De-dupe, stable order.
    seen: set[str] = set()
    out: list[str] = []
    for m in models:
        if m not in seen:
            seen.add(m)
            out.append(m)
    return out


def _diverse_catalog(pid: str, *, prefer: str | None = None) -> list[str]:
    """Order a provider's models so successive picks change family."""
    models = models_for_provider(pid)
    if prefer and prefer not in models:
        models = [prefer, *models]
    if not models:
        return [prefer] if prefer else []
    chosen: list[str] = []
    used_families: set[str] = set()
    rest = list(models)
    if prefer and prefer in rest:
        chosen.append(prefer)
        used_families.add(model_family(prefer))
        rest = [m for m in rest if m != prefer]
    # Greedy: next unused family, then leftovers.
    while rest:
        nxt = next((m for m in rest if model_family(m) not in used_families), None)
        if nxt is None:
            chosen.extend(rest)
            break
        chosen.append(nxt)
        used_families.add(model_family(nxt))
        rest = [m for m in rest if m != nxt]
    return chosen


def pair_key(provider_id: str, model: str | None) -> str:
    return f"{provider_id}/{model or 'default'}"


def model_strength(model: str | None) -> float:
    """0..1 flagship heuristic for the effort slider's strength band.

    Cheap/small ids score low; opus / gpt-5.x / grok-4 score high.
    Not billed cost — Copilot is still one subscription. Local 7B-class
    names score like mini so Maximum does not treat them as flagship.
    """
    m = (model or "").strip().lower()
    if not m:
        return 0.35
    token = m.partition("/")[2] or m
    score = 0.48
    cheap = any(
        s in token
        for s in (
            "mini", "nano", "haiku", "flash", "small", "tiny", "lite", "luna",
        )
    )
    size = re.search(r"(\d+)\s*b\b", token)
    if size:
        n = int(size.group(1))
        if n <= 8:
            cheap = True
            score -= 0.08
        elif n >= 27:
            score += 0.12
    if cheap:
        score -= 0.22
    else:
        if any(
            s in token
            for s in ("opus", "o3", "o1", "gpt-5.5", "gpt-5.4", "gpt-5", "grok-4", "ultra")
        ):
            score += 0.28
        elif (
            "sonnet" in token
            or token.endswith("-pro")
            or "-pro-" in token
            or "pro-preview" in token
        ):
            score += 0.18
        elif "gemini" in token:
            score += 0.12
    return max(0.05, min(1.0, score))


def _clean_model_keys(raw: object) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    if not isinstance(raw, (list, tuple)):
        return out
    for item in raw:
        key = str(item or "").strip()
        if key and key not in seen:
            seen.add(key)
            out.append(key)
    return out


def _workspace_denied_path(workspace: Path) -> Path:
    return Path(workspace) / ".workbench" / "state" / "orchestration.json"


def _read_workspace_denied(workspace: Path) -> list[str] | None:
    """None = this desk has no file yet (inherit the global seed)."""
    path = _workspace_denied_path(workspace)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("denied_models")
    if not isinstance(raw, list):
        return []
    return _clean_model_keys(raw)


def _write_workspace_denied(workspace: Path, keys: list[str]) -> None:
    path = _workspace_denied_path(workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                existing = loaded
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing["denied_models"] = keys
    atomicio.write_json_atomic(path, existing)


def get_denied_models(workspace: Path | None = None) -> list[str]:
    """``provider/model`` keys the chief of staff may not use.

    Per workspace (``.workbench/state/orchestration.json``). Empty = every
    keyed catalog row is allowed. New catalog entries stay allowed until
    the user unchecks them on that workspace's Agent Dashboard. Desks
    without a file inherit the global ``settings.json`` seed.
    """
    if workspace is not None:
        loaded = _read_workspace_denied(workspace)
        if loaded is not None:
            return loaded
    from .. import app_settings
    return _clean_model_keys(app_settings.load().get("orchestration_denied_models"))


def set_denied_models(
    keys: list[str] | tuple[str, ...] | None,
    workspace: Path | None = None,
) -> list[str]:
    cleaned = _clean_model_keys(keys)
    if workspace is not None:
        _write_workspace_denied(workspace, cleaned)
        return cleaned
    from .. import app_settings
    data = app_settings.load()
    if cleaned:
        data["orchestration_denied_models"] = cleaned
    else:
        data.pop("orchestration_denied_models", None)
    app_settings.save(data)
    return cleaned


def model_allowed(
    provider_id: str,
    model: str | None,
    denied: list[str] | tuple[str, ...] | set[str] | None = None,
) -> bool:
    if not provider_id:
        return False
    blocked = set(denied if denied is not None else get_denied_models())
    if not blocked:
        return True
    if provider_id in blocked or f"{provider_id}/*" in blocked:
        return False
    return pair_key(provider_id, model) not in blocked


def set_model_allowed(
    key: str,
    allowed: bool,
    workspace: Path | None = None,
) -> list[str]:
    """Toggle one catalog key. Refuses to deny the last remaining model."""
    key = str(key or "").strip()
    denied = set(get_denied_models(workspace))
    if not key:
        return sorted(denied)
    if allowed:
        denied.discard(key)
        return set_denied_models(sorted(denied), workspace=workspace)
    catalog = list_orchestrator_catalog(workspace=workspace)
    currently = [row for row in catalog if row.get("allowed")]
    if len(currently) <= 1 and currently and currently[0].get("key") == key:
        return sorted(denied)
    denied.add(key)
    return set_denied_models(sorted(denied), workspace=workspace)


def deny_provider(provider_id: str, workspace: Path | None = None) -> list[str]:
    """Uncheck every catalog row for one provider.

    Keeps the last remaining allowed model if this provider is the only
    one still on — Auto must have somewhere to land.
    """
    pid = str(provider_id or "").strip()
    catalog = list_orchestrator_catalog(workspace=workspace)
    mine = [row for row in catalog if str(row.get("provider") or "") == pid]
    others_on = [
        row for row in catalog
        if str(row.get("provider") or "") != pid and row.get("allowed")
    ]
    denied = set(get_denied_models(workspace))
    if not pid or not mine:
        return sorted(denied)
    keep_key: str | None = None
    if not others_on:
        keep = next((row for row in mine if row.get("allowed")), None)
        keep_key = str(keep.get("key") or "") if keep else None
    for row in mine:
        key = str(row.get("key") or "")
        if key and key != keep_key:
            denied.add(key)
    return set_denied_models(sorted(denied), workspace=workspace)


def list_orchestrator_catalog(
    *,
    available: list[tuple[str, str]] | None = None,
    denied: list[str] | None = None,
    workspace: Path | None = None,
) -> list[dict[str, Any]]:
    """Keyed (provider, model) rows the dashboard can check or uncheck."""
    from .. import admin_policy, llmgateway
    blocked = denied if denied is not None else get_denied_models(workspace)
    keyed = (
        available if available is not None
        else list_keyed_providers(scan_local_disk=False)
    )
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pid, default_m in keyed:
        if not pid or not admin_policy.provider_allowed(pid):
            continue
        models = models_for_provider(pid)
        if default_m and default_m not in models:
            models = [default_m, *models]
        if not models:
            models = [default_m or "default"]
        try:
            label = str(llmgateway.get(pid).LABEL)
        except Exception:  # noqa: BLE001
            label = pid
        cat = provider_category(pid)
        local = pid in LOCAL_PROVIDER_IDS or cat == "local"
        for model in models:
            key = pair_key(pid, model)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "key": key,
                "provider": pid,
                "provider_label": label,
                "model": model,
                "category": cat or ("local" if local else ""),
                "local": local,
                "allowed": model_allowed(pid, model, blocked),
                "strength": round(model_strength(model), 3),
            })
    return rows


def _catalog_pairs(
    pid: str,
    *,
    prefer: str | None,
    denied: list[str] | tuple[str, ...] | set[str],
) -> list[tuple[str, str | None]]:
    from .. import admin_policy
    if not pid or not admin_policy.provider_allowed(pid):
        return []
    out: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()
    for model in _diverse_catalog(pid, prefer=prefer):
        if not model_allowed(pid, model, denied):
            continue
        pair = (pid, model)
        if pair not in seen:
            seen.add(pair)
            out.append(pair)
    if prefer and model_allowed(pid, prefer, denied):
        pair = (pid, prefer)
        if pair not in seen:
            out.insert(0, pair)
    return out


def _rank_pairs(
    pairs: list[tuple[str, str | None]],
    *,
    preference: float,
    roster: list[tuple[str, str | None]] | None = None,
    chief: tuple[str, str | None] | None = None,
) -> list[tuple[str, str | None]]:
    """Worker ranking: independence first, then slider + token efficiency.

    Local backends are treated as maximally token-efficient (strength 0)
    at a quality/speed cost that depends on the box and the weights.
    Economy therefore prefers them for extra tasks; Maximum still uses
    them when a leftover slot needs a cheap independent opinion.
    """
    s = clamp_preference(preference)
    target = 0.22 + 0.70 * s
    roster_set = set(roster or [])
    chief_fam = model_family(chief[1]) if chief else ""
    chief_pid = chief[0] if chief else ""
    def _key(pair: tuple[str, str | None]) -> tuple[Any, ...]:
        pid, model = pair
        local = pid in LOCAL_PROVIDER_IDS or provider_category(pid) == "local"
        st = 0.0 if local else model_strength(model)
        dist = abs(st - target)
        same_fam = (
            1 if chief and pid == chief_pid and model_family(model) == chief_fam
            else 0
        )
        in_roster = 0 if pair in roster_set else 1
        # Tie-break: Maximum prefers the stronger of two equally close
        # models; Economy prefers the cheaper.
        pull = -st if s >= 0.5 else st
        return (same_fam, dist, in_roster, pull)
    return sorted(pairs, key=_key)


def _diverse_assign(
    ranked: list[tuple[str, str | None]],
    n: int,
) -> list[tuple[str, str | None]]:
    """Fill n slots with unused (provider, family) pairs, then leftovers."""
    if not ranked:
        return []
    n = max(1, n)
    out: list[tuple[str, str | None]] = []
    used_fam: set[tuple[str, str]] = set()
    used_pair: set[tuple[str, str | None]] = set()
    for pair in ranked:
        fam = (pair[0], model_family(pair[1]))
        if fam in used_fam:
            continue
        out.append(pair)
        used_fam.add(fam)
        used_pair.add(pair)
        if len(out) >= n:
            return out
    rest = [p for p in ranked if p not in used_pair] or ranked
    i = 0
    while len(out) < n:
        out.append(rest[i % len(rest)])
        i += 1
    return out


def allocate_models(
    n: int,
    *,
    independence: str,
    preference: float,
    default_provider: str,
    default_model: str | None,
    workspace: Path,
    available: list[tuple[str, str]] | None = None,
    playbook_roster: list[tuple[str, str | None]] | None = None,
    bucket: str = "",
    denied_models: list[str] | None = None,
) -> list[tuple[str, str | None]]:
    """Diversity-aware (provider, model) assignment.

    Channel layer (who can talk) is separate from policy (what to buy):

    * the rail picker is the **chief** — questions, ``/curate``, and
      the chief of staff run on that pair when it is allowed;
    * extra task slots (investigators, CE workers, verifiers) come
      from the dashboard allowlist when they add opinion independence
      or token efficiency;
    * local backends are maximally token-efficient (quality/speed
      depend on the box and the weights);
    * per-workspace dashboard denylist is the user-facing allowlist
      for those extra slots;
    * last-good desk roster is a sort hint among allowed remotes;
    * cooled-down probes (weekly limit, dead local server) are skipped;
    * the effort slider picks a strength band for **workers**
      (Economy = cheaper / local, Maximum = flagship) and how much
      independent fan-out to buy;
    * the CE model ladder is not consulted — Auto owns this roster.

    Intra-provider catalogs (Copilot GPT vs Claude vs Gemini) still
    supply independence when only one provider is keyed. Admin policy
    is authoritative. Fail-soft if the catalog has only one model.
    """
    from .. import admin_policy, orchestrator_fs
    from . import orchestration_health as health
    n = max(1, n)
    default = (default_provider, default_model)
    denied = (
        denied_models if denied_models is not None
        else get_denied_models(workspace)
    )

    keyed = available
    if keyed is None:
        if os.environ.get("PYTEST_CURRENT_TEST"):
            keyed = [(default_provider, default_model or "")] if default_provider else []
        else:
            keyed = list_keyed_providers()

    pids: list[str] = []
    hint_by_pid: dict[str, str | None] = {}
    for pid, model in keyed:
        if not pid:
            continue
        if pid not in pids:
            pids.append(pid)
        hint_by_pid.setdefault(pid, model)
    if default_provider and default_provider not in pids:
        pids.insert(0, default_provider)
        hint_by_pid[default_provider] = default_model
    elif default_provider and default_model and not hint_by_pid.get(default_provider):
        hint_by_pid[default_provider] = default_model

    roster = playbook_roster
    if roster is None:
        try:
            roster = orchestrator_fs.preferred_roster(workspace, bucket=bucket)
        except Exception:  # noqa: BLE001
            roster = []

    remote_pids = [
        pid for pid in pids
        if provider_category(pid) != "local" and pid not in LOCAL_PROVIDER_IDS
    ]
    local_pids = [
        pid for pid in pids
        if pid not in remote_pids
    ]

    pool: list[tuple[str, str | None]] = []
    seen: set[tuple[str, str | None]] = set()

    def _extend(pid: str, *, require_health: bool) -> None:
        if not pid or not admin_policy.provider_allowed(pid):
            return
        if require_health and not health.is_available(pid):
            return
        prefer = hint_by_pid.get(pid)
        if pid == default_provider and default_model:
            prefer = default_model
        for pair in _catalog_pairs(pid, prefer=prefer, denied=denied):
            if pair not in seen:
                seen.add(pair)
                pool.append(pair)

    for pid in remote_pids + local_pids:
        _extend(pid, require_health=True)
    if not pool:
        for pid in remote_pids + local_pids:
            _extend(pid, require_health=False)
    if not pool:
        if admin_policy.provider_allowed(default_provider) and model_allowed(
            default_provider, default_model, denied,
        ):
            pool = [default]
        else:
            pool = [default]

    ranked = _rank_pairs(pool, preference=preference, roster=list(roster or []))
    if not ranked:
        ranked = [default]

    chief: tuple[str, str | None] | None = None
    if (
        default_provider
        and admin_policy.provider_allowed(default_provider)
        and model_allowed(default_provider, default_model, denied)
    ):
        chief = default
    if chief is None:
        chief = ranked[0]

    if n == 1 or independence == "low":
        return [chief] * n

    ranked_workers = _rank_pairs(
        [p for p in pool if p != chief] or pool,
        preference=preference,
        roster=list(roster or []),
        chief=chief,
    )
    workers = _diverse_assign(ranked_workers, n - 1)
    return [chief] + workers


def pick_chief_pair(
    *,
    default_provider: str,
    default_model: str | None,
    preference: float,
    workspace: Path,
    available: list[tuple[str, str]] | None = None,
    denied_models: list[str] | None = None,
) -> tuple[str, str | None]:
    """Rail-picker pair for the chief / a one-node Auto or CE curator run.

    Extra workers still fan out via ``allocate_models`` / ``allocate_unused``.
    """
    alloc = allocate_models(
        1,
        independence="low",
        preference=preference,
        default_provider=default_provider,
        default_model=default_model,
        workspace=workspace,
        available=available,
        denied_models=denied_models,
    )
    return alloc[0]


def format_allocation_notice(
    allocations: list[tuple[str, str | None]],
    *,
    rail_provider: str,
    rail_model: str | None,
    skipped: list[str] | None = None,
) -> str:
    """Rail-facing explanation so a non-picker worker is not a surprise."""
    uniq: list[str] = []
    seen: set[tuple[str, str | None]] = set()
    for pid, model in allocations:
        key = (pid, model)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(f"{pid}/{model or 'default'}")
    rail = f"{rail_provider}/{rail_model or 'default'}"
    foreign = any(p != rail_provider for p, _ in allocations)
    parts: list[str] = []
    if foreign:
        parts.append(
            "Testing provider availability for independent workers — "
            f"your rail picker stays {rail}."
        )
        parts.append("Roster: " + " · ".join(uniq) + ".")
    if skipped:
        parts.append("Skipping " + "; ".join(skipped) + ".")
    return " ".join(parts).strip()


def allocate_unused(
    n: int,
    used: list[tuple[str, str | None]] | None = None,
    **kwargs: Any,
) -> list[tuple[str, str | None]]:
    """Next n (provider, model) pairs not already assigned.

    Prefers unused families so a verifier or expansion investigator is
    a new information path, not a copy of an existing worker.
    """
    n = max(1, int(n))
    used_list = list(used or [])
    used_set = set(used_list)
    pool = allocate_models(max(n + len(used_set) + 2, n), **kwargs)
    unused = [p for p in pool if p not in used_set]
    src = unused or pool
    if not src:
        default = (kwargs.get("default_provider") or "", kwargs.get("default_model"))
        return [default] * n  # type: ignore[list-item]
    return [src[i % len(src)] for i in range(n)]


METHOD_HINTS = (
    "wiki-search: start with search_wiki / read_wiki_page; cite page paths.",
    "graph-neighborhood: walk wiki_neighbors and wiki_path; prefer linked pages.",
    "vault-sources: prefer ce_vault_search / source-backed pages.",
    "contradiction-seeking: look for claims that disagree; record contradicts[].",
)

METHOD_HINTS_FINANCE = (
    "filings: material changes in 10-K/10-Q/8-K; going concern, restatements, auditor changes.",
    "earnings: EPS/revenue vs consensus, guidance, tone vs prior period; cite the transcript.",
    "insider/13F: cluster buys/sells and new institutional positions; cite the form.",
    "sector: competitor, supplier, and regulatory moves that reprice the whole group.",
    "confirmation: a claim is high-conviction only with 2+ independent evidence paths.",
)

METHOD_HINTS_SCIENCE = (
    "prior-art: wiki/graph + sources for the hypothesis and known failure modes.",
    "protocol: methods, controls, instruments, and what would falsify the claim.",
    "measurement: data, units, replicates, and provenance of each number.",
    "contradiction-seeking: results that disagree with the hypothesis or each other.",
)


def method_hints_for(n: int, independence: str, features: TaskFeatures | None = None) -> list[str]:
    if n <= 1 or independence == "low":
        return [""] * n
    if features and features.finance:
        hints = list(METHOD_HINTS_FINANCE)
    elif features and features.science:
        hints = list(METHOD_HINTS_SCIENCE)
    else:
        hints = list(METHOD_HINTS)
    out: list[str] = []
    for i in range(n):
        out.append(hints[i % len(hints)])
    return out


_RETRIEVAL_EXTRA = {
    "wiki-search": "",
    "graph-neighborhood": "neighbors path linked",
    "vault-sources": "source evidence",
    "contradiction-seeking": "contradict disagree conflict",
    "filings": "10-K 10-Q 8-K filing",
    "earnings": "earnings EPS guidance transcript",
    "insider/13F": "Form 4 13F insider",
    "sector": "competitor sector regulatory",
    "confirmation": "independent corroboration",
    "prior-art": "prior art hypothesis",
    "protocol": "protocol controls method",
    "measurement": "measurement data units replicate",
}


def retrieval_query_for(objective: str, hint: str = "") -> str:
    """Short, method-specific retrieval query — not a copy of the prompt."""
    words = re.findall(r"[A-Za-z0-9_./-]{2,}", objective or "")
    core = " ".join(words[:12])
    head = (hint or "").split(":", 1)[0].strip().lower()
    extra = _RETRIEVAL_EXTRA.get(head, "")
    q = f"{core} {extra}".strip()
    return q[:240]


def _split_subproblems(text: str) -> list[str]:
    items = re.findall(r"(?:^|\n)\s*(?:\d+[\.\)]\s+|[-*]\s+)(.+)", text or "")
    cleaned = [i.strip() for i in items if i.strip() and len(i.strip()) > 8]
    if len(cleaned) >= 2:
        return cleaned
    parts = [p.strip() for p in re.split(r"(?<=[?])\s+", text or "") if p.strip()]
    questions = [p for p in parts if p.endswith("?") and len(p) > 8]
    if len(questions) >= 2:
        return questions
    return []


def decompose_tasks(
    objective: str,
    n: int,
    features: TaskFeatures | None = None,
) -> list[dict[str, Any]]:
    """Deterministic independent slices. No planner LLM.

    A planner would serialize the DAG and give every worker the same
    framing. Sub-questions become distinct objectives; remaining slots
    keep the original request but get distinct retrieval queries plus
    method hints applied later by the plan constructor.
    """
    n = max(1, int(n))
    if HARD_MAX_NODES > 0:
        n = min(HARD_MAX_NODES - 3 if HARD_MAX_NODES > 3 else HARD_MAX_NODES, n)
    obj = (objective or "").strip()
    slices = _split_subproblems(obj)
    independence = estimate_independence(features) if features else "medium"
    hints = method_hints_for(n, "high" if n > 1 else independence, features)
    diff = "hard" if features and features.difficulty >= 0.6 else "normal"
    tasks: list[dict[str, Any]] = []
    for i in range(n):
        hint = hints[i] if i < len(hints) else ""
        if i < len(slices):
            desc = (
                f"{obj}\n\nFocus independently on this subproblem only:\n"
                f"{slices[i]}"
            )
            rq = retrieval_query_for(slices[i], hint)
        else:
            desc = obj
            rq = retrieval_query_for(obj, hint)
        tasks.append({
            "description": desc,
            "difficulty": diff,
            "retrieval_query": rq,
        })
    return tasks


# ── expansion / stopping ───────────────────────────────────────────


@dataclass
class ExpansionDecision:
    expand: bool
    n_extra: int
    reason: str
    objectives: list[str] = field(default_factory=list)


def should_expand(
    *,
    preference: float,
    independence: str,
    allow_expand: bool,
    verification: dict[str, Any] | None,
    findings_n: int,
    expansions_so_far: int,
    nodes_so_far: int,
    remaining_nodes: int,
    consequence: float = 0.1,
    unique_sources: int | None = None,
) -> ExpansionDecision:
    """Buy another computation only if ΔU > threshold. Hard caps first."""
    return choose_expansion(
        preference=preference,
        independence=independence,
        allow_expand=allow_expand,
        verification=verification,
        findings_n=findings_n,
        expansions_so_far=expansions_so_far,
        nodes_so_far=nodes_so_far,
        remaining_nodes=remaining_nodes,
        consequence=consequence,
        unique_sources=unique_sources,
    )


def choose_expansion(
    *,
    preference: float,
    independence: str,
    allow_expand: bool,
    verification: dict[str, Any] | None,
    findings_n: int,
    expansions_so_far: int,
    nodes_so_far: int,
    remaining_nodes: int,
    consequence: float = 0.1,
    unique_sources: int | None = None,
    max_expansions: int | None = None,
) -> ExpansionDecision:
    """Is another computation worth buying at this slider position?"""
    if not allow_expand:
        return ExpansionDecision(False, 0, "expansion disabled by policy")
    cap = HARD_MAX_EXPANSIONS if max_expansions is None else int(max_expansions)
    if cap > 0 and expansions_so_far >= cap:
        return ExpansionDecision(False, 0, "expansion cap reached")
    if remaining_nodes < 2:
        return ExpansionDecision(False, 0, "node budget exhausted")
    if HARD_MAX_NODES > 0 and nodes_so_far + 2 > HARD_MAX_NODES:
        return ExpansionDecision(False, 0, "node budget exhausted")
    s = clamp_preference(preference)
    v = verification or {}
    unresolved = v.get("unresolved") or []
    if not isinstance(unresolved, list):
        unresolved = []

    kw = dict(
        verification=v, findings_n=findings_n, consequence=consequence,
        unique_sources=unique_sources, nodes_so_far=nodes_so_far,
    )
    # Rank actions by ΔU. A redundant copy of the same path is last.
    action = "diverse_investigator" if independence != "low" else "investigator"
    dq = util.estimate_marginal_quality(action=action, **kw)
    dc, dl = util.estimate_marginal_cost_latency(action)
    du = util.marginal_utility(dq, dc, dl, s)
    dq0 = util.estimate_marginal_quality(action="redundant_copy", **kw)
    du0 = util.marginal_utility(
        dq0, *util.estimate_marginal_cost_latency("redundant_copy"), s,
    )
    if dq0 >= dq and du0 <= util.EXPANSION_THRESHOLD:
        # Identical extra worker is not worth it; the diverse one might be.
        pass
    # Same remaining gaps on a later wave are worth less. This is the
    # formula tightening — not a spawn cap. A ballooning DAG means
    # this decay is too weak.
    du -= 0.045 * max(0, expansions_so_far)
    if du <= util.EXPANSION_THRESHOLD:
        return ExpansionDecision(
            False, 0,
            f"ΔU={du:.3f} ≤ threshold (ΔQ={dq:.3f}); stop",
        )

    objectives: list[str] = []
    reasons: list[str] = []
    conflicts = int(v.get("conflicts") or 0)
    unsupported = int(v.get("unsupported") or 0)
    if conflicts > 0:
        reasons.append(f"{conflicts} verification conflict(s)")
        objectives.append(
            "Resolve conflicting findings using source evidence. "
            "Re-read the cited pages and report which claim is supported."
        )
    if unsupported > 0 and findings_n > 0 and unsupported / max(1, findings_n) >= 0.4:
        reasons.append(f"{unsupported} unsupported finding(s)")
        objectives.append(
            "Gather additional evidence for claims currently marked "
            "insufficient. Cite sources; do not restate unsupported claims."
        )
    if unresolved:
        reasons.append(f"{len(unresolved)} unresolved item(s)")
        for u in unresolved[:2]:
            objectives.append(f"Investigate unresolved point: {str(u)[:240]}")
    try:
        conf = float(v.get("confidence") or 0.0)
    except (TypeError, ValueError):
        conf = 0.0
    if conf < 0.4 and findings_n >= 2:
        reasons.append(f"low verifier confidence ({conf:.2f})")
        objectives.append(
            "Independent second look at the original question; "
            "focus on evidence the first pass missed."
        )
    if not objectives:
        objectives.append(
            "Independent second look at remaining gaps; cite sources."
        )
        reasons.append(f"ΔU={du:.3f}")
    extra = 1
    # A second extra worker is a *new* ΔU, not "Maximum means 2".
    room = remaining_nodes - 1
    if HARD_MAX_NODES > 0:
        room = min(room, HARD_MAX_NODES - nodes_so_far - 1)
    if extra < room:
        dq2 = util.estimate_marginal_quality(
            action="redundant_copy" if independence == "low" else "investigator",
            **kw,
        )
        dc2, dl2 = util.estimate_marginal_cost_latency("investigator")
        if util.marginal_utility(dq2, dc2, dl2, s) > util.EXPANSION_THRESHOLD:
            extra = 2
    extra = min(extra, room)
    if extra < 1:
        return ExpansionDecision(False, 0, "no room for extra nodes")
    return ExpansionDecision(True, extra, "; ".join(reasons) or f"ΔU={du:.3f}", objectives[:extra])


def should_continue(
    *,
    preference: float,
    allow_expand: bool,
    objective_met: bool | None,
    gap: str = "",
    verification: dict[str, Any] | None = None,
    findings_n: int = 0,
    expansions_so_far: int = 0,
    nodes_so_far: int = 0,
    remaining_nodes: int = 0,
    consequence: float = 0.1,
    unique_sources: int | None = None,
    last_wave_new_findings: int = 1,
    concat: bool = False,
) -> ExpansionDecision:
    """After a synthesizer: keep going only with an explicit 'no' *and* ΔU.

    Missing stop token → auto-stop (do not idle overnight by accident).
    Concat fan-out is a compatibility terminal merge.
    """
    if concat:
        return ExpansionDecision(False, 0, "concat merge is terminal")
    if objective_met is True:
        return ExpansionDecision(False, 0, "OBJECTIVE_MET: yes")
    if objective_met is None:
        return ExpansionDecision(False, 0, "no stop token; auto-stop")
    if last_wave_new_findings <= 0:
        return ExpansionDecision(False, 0, "no new evidence this wave")
    if not allow_expand:
        return ExpansionDecision(False, 0, "expansion disabled by policy")
    if HARD_MAX_CONTINUATIONS > 0 and expansions_so_far >= HARD_MAX_CONTINUATIONS:
        return ExpansionDecision(False, 0, "continuation cap reached")
    v = dict(verification or {})
    gap_s = (gap or "").strip()
    if gap_s:
        unresolved = list(v.get("unresolved") or [])
        if not isinstance(unresolved, list):
            unresolved = []
        unresolved.append(gap_s)
        v["unresolved"] = unresolved
        try:
            conf = float(v.get("confidence") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        if conf >= 0.85:
            # Synthesizer still sees a gap — don't let a high verifier
            # score hide it from ΔU.
            v["confidence"] = min(conf, 0.5)
    return choose_expansion(
        preference=preference,
        independence="high",
        allow_expand=allow_expand,
        verification=v,
        findings_n=findings_n,
        expansions_so_far=expansions_so_far,
        nodes_so_far=nodes_so_far,
        remaining_nodes=remaining_nodes,
        consequence=consequence,
        unique_sources=unique_sources,
        max_expansions=HARD_MAX_CONTINUATIONS,
    )


# ── telemetry + bandit state ───────────────────────────────────────


def policy_path(workspace: Path | None = None) -> Path:
    """Learned recipe weights. Per-workspace when ``workspace`` is set.

    Machine-local (statedir), not ``.orchestrator/`` — regenerable, must
    not ride iCloud/OneDrive. A missing file is priors, not an error.
    The legacy ``state_root()/orchestration_policy.json`` (no workspace)
    is only for tests and pre-0.9.19 leftovers; the daemon always
    passes the active vault.
    """
    if workspace is not None:
        return statedir.workspace_state_dir(workspace) / "orchestration_policy.json"
    return statedir.state_root() / "orchestration_policy.json"


def telemetry_path(workspace: Path | None = None) -> Path:
    if workspace is not None:
        return statedir.workspace_state_dir(workspace) / "orchestration_telemetry.jsonl"
    return statedir.state_root() / "orchestration_telemetry.jsonl"


def empty_state() -> dict[str, Any]:
    return {
        "version": POLICY_VERSION,
        "updated_at": time.time(),
        "buckets": {},
        "totals": {"orchestrations": 0, "explorations": 0, "resets": 0},
    }


def load_state(workspace: Path | None = None) -> dict[str, Any]:
    p = policy_path(workspace)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return empty_state()
    if not isinstance(data, dict) or data.get("version") != POLICY_VERSION:
        log.warning("orchestration policy state missing/incompatible; using defaults")
        return empty_state()
    data.setdefault("buckets", {})
    data.setdefault("totals", {"orchestrations": 0, "explorations": 0, "resets": 0})
    return data


def save_state(state: dict[str, Any], workspace: Path | None = None) -> None:
    state = dict(state)
    state["version"] = POLICY_VERSION
    state["updated_at"] = time.time()
    p = policy_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomicio.write_json_atomic(p, state)


def reset_state(workspace: Path | None = None) -> dict[str, Any]:
    prev = load_state(workspace)
    st = empty_state()
    st["totals"]["resets"] = int((prev.get("totals") or {}).get("resets") or 0) + 1
    save_state(st, workspace)
    return st


def inspect_state(workspace: Path | None = None) -> dict[str, Any]:
    """Safe diagnostics for Settings / debug. No secrets."""
    st = load_state(workspace)
    buckets = st.get("buckets") or {}
    summary = []
    for key, rec in list(buckets.items())[:40]:
        if not isinstance(rec, dict):
            continue
        arms = rec.get("arms") or {}
        rows = []
        for arm, stats in arms.items():
            if not isinstance(stats, dict):
                continue
            n = int(stats.get("n") or 0)
            mean = (float(stats.get("sum_reward") or 0.0) / n) if n else None
            rows.append({
                "arm": arm, "n": n, "mean_reward": mean,
                "sum_quality": stats.get("sum_quality"),
                "sum_cost": stats.get("sum_cost"),
            })
        summary.append({"bucket": key, "arms": rows})
    return {
        "version": st.get("version"),
        "updated_at": st.get("updated_at"),
        "scope": "workspace" if workspace is not None else "machine",
        "workspace": str(workspace) if workspace is not None else None,
        "totals": st.get("totals"),
        "buckets": summary,
        "hard_bounds": {
            "max_nodes": HARD_MAX_NODES,
            "max_depth": HARD_MAX_DEPTH,
            "max_concurrency": HARD_MAX_CONCURRENCY,
            "max_expansions": HARD_MAX_EXPANSIONS,
            "max_continuations": HARD_MAX_CONTINUATIONS,
            "wall_clock_sec": HARD_WALL_CLOCK_SEC,
            "worker_timeout_sec": HARD_WORKER_TIMEOUT_SEC,
        },
        "utility": {
            "lambda_c_floor": util.LAMBDA_C_FLOOR,
            "lambda_c_max": util.LAMBDA_C_MAX,
            "lambda_l_floor": util.LAMBDA_L_FLOOR,
            "lambda_l_max": util.LAMBDA_L_MAX,
            "expansion_threshold": util.EXPANSION_THRESHOLD,
        },
        "channels": _inspect_channels(),
    }


def _inspect_channels() -> dict[str, Any]:
    try:
        from . import orchestration_health as health
        return health.inspect()
    except Exception:  # noqa: BLE001
        return {"providers": []}


def _utility(
    *,
    quality: float,
    cost_tokens: float,
    latency_s: float,
    preference: float,
) -> float:
    return util.realized_utility(
        quality=quality, cost_tokens=cost_tokens,
        latency_s=latency_s, preference=preference,
    )


def quality_proxy(telemetry: dict[str, Any]) -> float:
    """Quality from artifacts and use, not from a Reviews queue.

    Agent agreement and raw node count are not quality. Verifier
    confidence only counts when unsupported claims are not dominating.
    Correlated extra workers (more nodes than distinct sources) are
    penalised so the learner does not conclude that bigger swarms win.
    Provider outages (``worker_failures`` from a weekly limit) are
    *not* quality — those live on the channel-health TTL, or the
    bandit would unlearn diversity whenever Claude is quota'd.

    Human Reviews accept/reject is ignored: people will not grade
    every page. Signal is wiki/report pages that *landed* this run
    and desk pages *reused* as sources on a later run. Dismiss is
    an undo (drop from desk inventory), not a training label.
    """
    if telemetry.get("cancelled"):
        return 0.0
    q = 0.55
    if telemetry.get("completed"):
        q += 0.2
    unsupported = int(telemetry.get("unsupported_rejected") or 0)
    findings = max(1, int(
        telemetry.get("candidate_findings_n") or telemetry.get("findings_n") or 1,
    ))
    vc = telemetry.get("verifier_confidence")
    try:
        if vc is not None and unsupported / findings <= 0.4:
            q += 0.15 * max(0.0, min(1.0, float(vc)))
    except (TypeError, ValueError):
        pass
    q -= 0.25 * min(1.0, unsupported / findings)
    conflicts = int(telemetry.get("verification_conflicts") or 0)
    q -= 0.15 * min(1.0, conflicts / findings)
    if telemetry.get("retry_after"):
        q -= 0.25
    if telemetry.get("deterministic_ok"):
        q += 0.2
    unique_sources = telemetry.get("unique_sources")
    nodes = int(telemetry.get("final_nodes") or 0)
    if unique_sources is not None and nodes > 1:
        try:
            us = int(unique_sources)
        except (TypeError, ValueError):
            us = -1
        if us >= 0 and us < max(1, nodes - 1):
            q -= 0.08 * min(1.0, (nodes - 1 - us) / max(1, nodes))
    try:
        pages = max(0, int(telemetry.get("wiki_pages_landed") or 0))
    except (TypeError, ValueError):
        pages = 0
    try:
        reports = max(0, int(telemetry.get("reports_landed") or 0))
    except (TypeError, ValueError):
        reports = 0
    try:
        reused = max(0, int(telemetry.get("reused_desk_sources") or 0))
    except (TypeError, ValueError):
        reused = 0
    q += 0.05 * min(4, pages)
    if reports:
        q += 0.08
    q += 0.04 * min(4, reused)
    return max(0.0, min(1.2, q))


def record_outcome(
    telemetry: dict[str, Any], workspace: Path | None = None,
) -> None:
    """Append a telemetry row and update the bandit. Fail-soft."""
    try:
        _record_outcome_inner(telemetry, workspace)
    except Exception:  # noqa: BLE001
        log.exception("orchestration telemetry record failed")


def _record_outcome_inner(
    telemetry: dict[str, Any], workspace: Path | None = None,
) -> None:
    row = dict(telemetry)
    row.setdefault("recorded_at", time.time())
    # Never persist secrets or chain-of-thought.
    row.pop("transcripts", None)
    row.pop("system", None)
    p = telemetry_path(workspace)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")

    features = TaskFeatures.from_dict(row.get("features") or {})
    arm = str(row.get("arm_id") or "single")
    pref = clamp_preference(row.get("preference", features.preference))
    quality = quality_proxy(row)
    tokens = float(row.get("tokens") or 0)
    latency = float(row.get("latency_s") or 0)
    reward = _utility(
        quality=quality, cost_tokens=tokens, latency_s=latency, preference=pref,
    )
    # Marginal yield (for diminishing-returns visibility).
    nodes = max(1, int(row.get("final_nodes") or 1))
    row_mg = quality / nodes
    st = load_state(workspace)
    bucket = str(row.get("bucket") or features.bucket())
    buckets = st.setdefault("buckets", {})
    rec = buckets.setdefault(bucket, {"arms": {}})
    arms = rec.setdefault("arms", {})
    stats = arms.setdefault(arm, {
        "n": 0, "sum_reward": 0.0, "sum_quality": 0.0,
        "sum_cost": 0.0, "sum_latency": 0.0, "sum_nodes": 0.0,
        "sum_quality_per_node": 0.0,
    })
    stats["n"] = int(stats.get("n") or 0) + 1
    stats["sum_reward"] = float(stats.get("sum_reward") or 0.0) + reward
    stats["sum_quality"] = float(stats.get("sum_quality") or 0.0) + quality
    stats["sum_cost"] = float(stats.get("sum_cost") or 0.0) + tokens
    stats["sum_latency"] = float(stats.get("sum_latency") or 0.0) + latency
    stats["sum_nodes"] = float(stats.get("sum_nodes") or 0.0) + nodes
    stats["sum_quality_per_node"] = float(stats.get("sum_quality_per_node") or 0.0) + row_mg
    totals = st.setdefault("totals", {"orchestrations": 0, "explorations": 0, "resets": 0})
    totals["orchestrations"] = int(totals.get("orchestrations") or 0) + 1
    if row.get("explored"):
        totals["explorations"] = int(totals.get("explorations") or 0) + 1
    save_state(st, workspace)


def get_preference() -> float:
    from .. import app_settings
    return clamp_preference(app_settings.load().get("orchestration_preference"), PREF_BALANCED)


def set_preference(value: float) -> float:
    from .. import app_settings
    v = clamp_preference(value)
    data = app_settings.load()
    data["orchestration_preference"] = v
    app_settings.save(data)
    return v


def preference_label(value: float) -> str:
    s = clamp_preference(value)
    if s <= 0.2:
        return "Economy"
    if s >= 0.8:
        return "Maximum"
    return "Balanced"
