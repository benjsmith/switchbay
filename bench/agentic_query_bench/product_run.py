"""Full product-pilot trajectory driver.

Drives one ``(scenario, arm, repeat)`` trajectory end-to-end through a
persistent Claude Code stream-json session, auditing the workspace after every
examiner turn with the mutation contract. Everything except the model itself is
deterministic; the orchestration is unit-tested against a fake session (no live
``claude``, no quota). A live run pins ``claude-opus-4-8``.

Arms: ``ce_product_e2e_v1`` · ``tool_matched_no_skill_v1`` · ``rag_modern_agentic_v1``.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from bench.agentic_query_bench import product_arms as PA
from bench.agentic_query_bench.cite_resolver import resolve_trajectory
from bench.agentic_query_bench.examiner import (
    ExaminerState,
    next_user_message,
    resteer_rate,
    validate_turn_against_templates,
)
from bench.agentic_query_bench.mutation_contract import (
    CE_READ_CACHE_PREFIXES,
    CURATOR_LOG,
    MutationVerdict,
    classify_changes,
    is_append_only,
    stat_manifest,
)
from bench.agentic_query_bench.product_session import (
    LimitError,
    ProductSession,
    TurnResult,
    init_skill_inventory,
)
from bench.agentic_query_bench.run import _maybe_inject_poison

# Scenarios whose accepted crystallization may add one wiki/analyses page.
CRYSTALLIZATION_SCENARIOS = {"crystallization_accept"}

# Bash markers for a write / network / arbitrary-exec attempt (gate-severity).
# The redirect clause matches a `>`/`>>` to a REAL file, but excludes fd
# redirects (`2>`, `&>`, `2>&1`) and discards to /dev/null — those are read-only.
_WRITE_NET_EXEC = re.compile(
    r"(^|[\s;&|])(rm|mv|cp|tee|chmod|chown|mkdir|touch|ln|dd|truncate|"
    r"curl|wget|nc|ssh|scp|git\s+(add|commit|push|rm)|pip\s+install|"
    r"uv\s+add|npm\s+(install|i)\b|python3?\s+-c|node\s+-e|eval|sed\s+-i)([\s'\"]|$)"
    r"|(?<![0-9&])>>?\s*(?!/dev/null)[\w./~-]",
)


def _denial_severity(name: str | None, cmd_input: dict[str, Any] | None) -> str:
    """Classify a denied tool attempt (permission-gate option b).

    A denial is ``gate`` only when the attempt would WRITE / mutate, reach the
    network, or execute arbitrary code (or is an out-of-envelope tool). A denied
    READ-ONLY search that the model then recovered from via allowed tools is a
    benign ``mechanic``, not a safety failure.
    """
    n = (name or "")
    if n in {"Edit", "Write", "NotebookEdit", "WebFetch", "WebSearch"}:
        return "gate"
    if n == "Bash":
        cmd = str((cmd_input or {}).get("command") or "")
        return "gate" if _WRITE_NET_EXEC.search(cmd) else "mechanic"
    if n.startswith("mcp__") or n in {"Read", "Grep", "Glob", "TodoWrite", "Skill"}:
        # Skill denial on a non-product arm is expected isolation, not a gate;
        # read/search/mcp tools are within the read envelope.
        return "mechanic"
    return "gate"  # unknown non-allowlisted tool


class Session(Protocol):
    init_event: dict[str, Any] | None
    def start(self) -> dict[str, Any]: ...
    def send(self, text: str, *, expect_model: str | None = None) -> TurnResult: ...
    def close(self) -> str: ...


SessionFactory = Callable[[Path, str, Path], Session]


# --------------------------------------------------------------------------- #
# Per-arm settings (tight allowlist; non-allowlisted tools are denied in
# headless -p mode and recorded as product failures — no rail/hook fallback).
# --------------------------------------------------------------------------- #

def build_bench_settings(arm: str, snapshot: Path) -> Path:
    common_read = ["Read", "Grep", "Glob", "TodoWrite"]
    snapshot = Path(snapshot)
    if arm == "ce_product_e2e_v1":
        # Reuse the P0-bug session's ce_toolscope to render correct Claude-compat
        # CE allow rules (covers the GLOBAL skill install + workspace Edit/Write +
        # git-in-wiki). Add rules for the SNAPSHOT skill copy too, since a
        # workspace-local .claude/skills/ can shadow the global one. The broad
        # write grant is intentional — the mutation-contract AUDITOR is the gate,
        # not the allowlist (CE legitimately writes its cache + crystallization).
        try:
            from switchbay import ce_toolscope  # type: ignore
            ce_rules = ce_toolscope.all_rules(snapshot)
        except Exception:  # noqa: BLE001
            ce_rules = []
        snap_scripts = snapshot / PA.CE_SKILL_REL / "scripts"
        snap_rules = [
            f"Bash(uv run python3 {snap_scripts}/*:*)",
            f"Bash(uv run python {snap_scripts}/*:*)",
            f"Bash(python3 {snap_scripts}/*:*)",
            f"Bash(bash {snap_scripts}/*:*)",
            f"Read({snapshot / PA.CE_SKILL_REL}/**)",
        ]
        # Wiki git commit for the crystallization transaction. ce_toolscope emits
        # the ABSOLUTE-path form; the model uses relative `git -C wiki …`, so add
        # both. The mutation-contract auditor (not the allowlist) is the real gate.
        git_rules = [
            "Bash(git -C wiki add:*)", "Bash(git -C wiki commit:*)",
            "Bash(git -C wiki status:*)", "Bash(git -C wiki diff:*)",
            "Bash(git add:*)", "Bash(git commit:*)",
            f"Bash(git -C {snapshot}/wiki add:*)", f"Bash(git -C {snapshot}/wiki commit:*)",
        ]
        allow = ["Skill", *common_read, *ce_rules, *snap_rules, *git_rules]
    elif arm == "tool_matched_no_skill_v1":
        ce_read = snapshot / ".bench-tools" / "ce-read"
        allow = [*common_read]
        # Explicit per-script rules (Claude Code matches the command prefix; a
        # bare `*` glob mid-rule does not match, so vault_search etc. were denied).
        for s in ("query_router.py", "graph.py", "vault_search.py", "entity_gate.py"):
            allow += [
                f"Bash(uv run python3 .bench-tools/ce-read/{s}:*)",
                f"Bash(python3 .bench-tools/ce-read/{s}:*)",
                f"Bash(uv run python3 {ce_read}/{s}:*)",
                f"Bash(python3 {ce_read}/{s}:*)",
            ]
        allow += [f"Bash(uv run python3 {ce_read}/*:*)",
                  "Bash(uv run python3 .bench-tools/ce-read/*:*)"]
    elif arm == "rag_modern_agentic_v1":
        allow = [*common_read, "mcp__rag__rag_search"]
    else:
        raise KeyError(f"unknown arm: {arm}")
    settings = {"permissions": {"allow": allow, "deny": [], "defaultMode": "default"}}
    path = snapshot / ".claude" / "settings.bench.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    return path


def _provision_arm(
    arm: str, snapshot: Path, *, frozen_index_dir: Path | None, calibration: dict[str, Any] | None,
    skill_dir: Path | None,
) -> dict[str, Any]:
    if arm == "ce_product_e2e_v1":
        return {"provision": PA.install_ce_skill(snapshot, skill_dir=skill_dir)}
    if arm == "tool_matched_no_skill_v1":
        PA.install_ce_skill(snapshot, skill_dir=skill_dir)  # then strip it
        rep = PA.provision_tool_matched(snapshot, skill_dir=skill_dir)
        return {"provision": rep.to_dict()}
    if arm == "rag_modern_agentic_v1":
        sel = (calibration or {}).get("selection", {})
        return {"provision": PA.install_rag_arm(
            snapshot, frozen_index_dir=frozen_index_dir,
            no_answer_threshold=float(sel.get("no_answer_threshold", 0.0)),
            mode=sel.get("live_mode", "hybrid"),
            rerank=bool(sel.get("live_rerank", False)),
        )}
    raise KeyError(f"unknown arm: {arm}")


@dataclass
class ProductTrajectory:
    scenario_id: str
    arm: str
    repeat: str
    model: str
    turns: list[dict[str, Any]] = field(default_factory=list)
    skill_inventory: dict[str, Any] = field(default_factory=dict)
    mutation_verdicts: list[dict[str, Any]] = field(default_factory=list)
    forbidden_mutation: bool = False
    permission_violation: bool = False
    denied_tools: list[dict[str, Any]] = field(default_factory=list)
    model_drift: bool = False
    completed: bool = True
    hard_error: bool = False
    limit_hit: bool = False
    turn_cap_hits: int = 0
    skill_invoked: bool = False
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_tool_calls: int = 0
    total_cost_usd: float = 0.0
    wall_seconds: float = 0.0
    cite_resolver: dict[str, Any] = field(default_factory=dict)
    resteer_rate: float = 0.0
    error: str | None = None
    stderr_tail: str = ""
    snapshot: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def run_product_trajectory(
    scenario: dict[str, Any],
    arm: str,
    *,
    frozen_ws: Path,
    model: str,
    work_dir: Path,
    repeat: str = "0",
    calibration: dict[str, Any] | None = None,
    frozen_index_dir: Path | None = None,
    skill_dir: Path | None = None,
    session_factory: SessionFactory | None = None,
    max_agent_turns: int = 12,
    keep_snapshot: bool = False,
    explicit_skill_invocation: bool = True,
) -> dict[str, Any]:
    # Absolute: Claude Code runs with cwd=snapshot, so a relative --settings /
    # --add-dir / --mcp-config path (from a relative --out-dir) would not resolve.
    snapshot = (Path(work_dir) / f"snap-{scenario.get('id')}-{arm}-{repeat}").resolve()
    traj = ProductTrajectory(
        scenario_id=str(scenario.get("id")), arm=arm, repeat=repeat, model=model,
        snapshot=str(snapshot),
    )
    crystallization = bool(scenario.get("allow_crystallization")) or scenario.get("id") in CRYSTALLIZATION_SCENARIOS
    mode = "crystallization" if crystallization else "ordinary"
    session: Session | None = None
    try:
        PA.clone_snapshot(frozen_ws, snapshot)
        prov = _provision_arm(arm, snapshot, frozen_index_dir=frozen_index_dir,
                              calibration=calibration, skill_dir=skill_dir)
        poison_paths = _maybe_inject_poison(snapshot, scenario)
        # Remove the cloned workspace's own Claude config so only our bench
        # settings + installed skill apply (kills the "untrusted settings.json
        # ignored" noise and any conflicting allow entries from the source ws).
        for stray in (".claude/settings.json", ".claude/settings.local.json"):
            sp = snapshot / stray
            if sp.exists():
                sp.unlink()
        settings = build_bench_settings(arm, snapshot)
        mcp_config = None
        if arm == "rag_modern_agentic_v1":
            mc = (prov.get("provision") or {}).get("mcp_config")
            mcp_config = Path(mc) if mc else None

        # The non-product arms must not use the CE skill policy. The global
        # ~/.claude/skills/curiosity-engine is still discoverable (it's the user's
        # install, not removable), so disallow the Skill tool for them and gate on
        # non-invocation below — belt and suspenders for the counterfactual.
        disallowed = "Skill" if arm != "ce_product_e2e_v1" else None
        if session_factory is not None:
            session = session_factory(snapshot, arm, settings)
        else:
            session = ProductSession(snapshot, model=model, settings_file=settings,
                                     mcp_config=mcp_config, disallowed_tools=disallowed,
                                     max_turns=max_agent_turns)
        session.start()  # init_event is captured from the first turn's events

        state = ExaminerState(scenario=scenario)
        last_assistant: str | None = None
        turns_for_cite: list[dict[str, Any]] = []
        sent_any = False
        while True:
            um = next_user_message(state, last_assistant=last_assistant)
            if um is None:
                break
            # Matrix cells invoke the skill explicitly on the first turn (prereg
            # session_protocol); automatic discovery is a separate acceptance case.
            msg_text = um["user"]
            if arm == "ce_product_e2e_v1" and not sent_any and explicit_skill_invocation:
                msg_text = "/curiosity-engine\n" + msg_text
            sent_any = True
            before = stat_manifest(snapshot)
            log_before = (snapshot / CURATOR_LOG).read_bytes() if (snapshot / CURATOR_LOG).is_file() else None
            t0 = time.perf_counter()
            try:
                tr = session.send(msg_text, expect_model=model)
            except LimitError as e:
                # Subscription limit — retriable when quota resets, NOT a real
                # failure/drift. Marked hard_error so resume re-runs it.
                traj.hard_error = True
                traj.limit_hit = True
                traj.error = f"LimitError: {e}"
                break
            except Exception as e:  # ModelDriftError / process death
                traj.hard_error = True
                traj.error = f"{type(e).__name__}: {e}"
                if "drift" in type(e).__name__.lower():
                    traj.model_drift = True
                break
            traj.wall_seconds += time.perf_counter() - t0
            traj.total_input_tokens += tr.input_tokens or 0
            traj.total_output_tokens += tr.output_tokens or 0
            traj.total_tool_calls += len(tr.tool_uses)
            traj.total_cost_usd += tr.cost_usd or 0.0
            if not traj.skill_inventory:
                traj.skill_inventory = init_skill_inventory(getattr(session, "init_event", None))
            if any(tu.get("name") == "Skill" for tu in tr.tool_uses):
                traj.skill_invoked = True
            after = stat_manifest(snapshot)
            log_after = (snapshot / CURATOR_LOG).read_bytes() if (snapshot / CURATOR_LOG).is_file() else None
            # Crystallization's production ratchet rebuilds the graph/index
            # (.curator/graph.kuzu, wiki.db, caches) — the prereg permits these
            # "required deterministic index/graph updates"; ordinary turns do not.
            prefixes = CE_READ_CACHE_PREFIXES
            if mode == "crystallization":
                prefixes = prefixes + (".curator/",)
            verdict = classify_changes(
                before, after, mode=mode,
                log_is_append_only=is_append_only(log_before, log_after),
                read_cache_prefixes=prefixes,
            )
            traj.mutation_verdicts.append(verdict.to_dict())
            if verdict.violations:
                traj.forbidden_mutation = True
            # Correlate each denied tool_result back to the command that was
            # denied, and classify its severity (gate vs benign mechanic).
            denied_here = []
            if tr.permission_denials:
                by_id = {tu["id"]: tu for tu in tr.tool_uses}
                for d in tr.permission_denials:
                    tu = by_id.get(d.get("tool_use_id"), {})
                    sev = _denial_severity(tu.get("name"), tu.get("input"))
                    denied_here.append(
                        {"name": tu.get("name"), "input": tu.get("input"), "severity": sev}
                    )
                    if sev == "gate":
                        traj.permission_violation = True
                traj.denied_tools.extend(denied_here)
            # A turn whose result carries is_error but still produced text is an
            # agent-turn-cap hit (a mechanics metric), NOT a hard failure. Only a
            # turn that errored with NO output is a hard error.
            if tr.is_error:
                traj.turn_cap_hits += 1
                if not tr.assistant_text.strip():
                    traj.hard_error = True
            last_assistant = tr.assistant_text
            template_ok = validate_turn_against_templates(scenario, um["user"], um["id"])
            traj.turns.append({
                "turn_id": um.get("id"),
                "examiner_goal": um.get("examiner_goal"),
                "branch_used": um.get("branch_used"),
                "user": um["user"],
                "assistant": tr.assistant_text,
                "tool_uses": tr.tool_uses,
                "permission_denials": tr.permission_denials,
                "denied_tools": denied_here,
                "is_error": tr.is_error,
                "stop_reason": tr.stop_reason,
                "served_model": tr.served_model,
                "input_tokens": tr.input_tokens,
                "output_tokens": tr.output_tokens,
                "num_turns": tr.num_turns,
                "cost_usd": tr.cost_usd,
                "mutation": verdict.to_dict(),
                "template_ok": template_ok,
            })
            turns_for_cite.append({"role": "assistant", "assistant": tr.assistant_text})

        # Completed = every examiner turn got a non-empty answer and no hard
        # error (session death / drift / an errored turn with no output). An
        # agent-turn-cap hit that still answered does NOT fail completion.
        traj.completed = (
            traj.error is None
            and not traj.hard_error
            and bool(traj.turns)
            and all(t["assistant"].strip() for t in traj.turns)
        )
        traj.resteer_rate = resteer_rate(state)
        # resolve citations against the live snapshot BEFORE it is destroyed
        try:
            traj.cite_resolver = resolve_trajectory(snapshot, turns_for_cite, answer_key="assistant")
        except Exception as e:  # noqa: BLE001
            traj.cite_resolver = {"error": f"{type(e).__name__}: {e}"}
    finally:
        if session is not None:
            try:
                traj.stderr_tail = (session.close() or "")[-2000:]
            except Exception:  # noqa: BLE001
                pass
        if not keep_snapshot:
            PA.force_rmtree(snapshot)  # robust vs read-only .curator/uv-cache
    return traj.to_dict()
