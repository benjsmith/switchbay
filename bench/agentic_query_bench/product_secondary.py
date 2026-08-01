"""Secondary qualitative analysis — Stage 1 (material generation), NATIVE protocol.

Per SCORED topic × arm × host model, one session poses the topic as a SYNTHESIS
query — the form that natively triggers CE's analysis-page offer (SKILL.md QUERY
step 7: synthesis fires it, task/recall does not). We then:
  • capture the synthesis-query REPLY (same framing across all three arms);
  • for CE only, let it OFFER + AUTHOR an analysis page NATIVELY — the accept turn
    defers to CE's own judgment ("if substantial enough to stand as an analysis
    page, file it; if it's just a lookup, no need"), so no page is ever forced;
    we record whether CE offered natively (before the accept turn) vs not, and
    only real, committed pages count;
  • pose an identical OFF-THE-LEASH follow-up to all three arms (reasoning +
    closed-book: propose sources / questions / hypotheses, flag what's not in
    the corpus) — a controlled, directional read of suppressed generativity.

No new matrix. Resumable (one JSON per unit). Stage 2 (4-judge pass + t-test) is
separate and gated.
"""

from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
from typing import Any

from bench.agentic_query_bench import product_arms as PA
from bench.agentic_query_bench import product_mechanics
from bench.agentic_query_bench.product_mechanics import _CRYSTALLIZE_OFFER
from bench.agentic_query_bench.product_run import run_product_trajectory

ROOT = Path(__file__).resolve().parent
SCORED = ["nc-absent-theme-quantum-01", "mp-poisoned-analysis-privacy-01",
          "ap-comp599-tech-debt-article-01", "rp-comp599-fairness-research-01"]
MODELS = ["claude-opus-4-8", "claude-opus-5"]
ARMS = ["ce_product_e2e_v1", "tool_matched_no_skill_v1", "rag_modern_agentic_v1"]

# Each scored topic reframed as a SYNTHESIS query (CE's native analysis trigger).
SYNTH_QUERIES = {
    "nc-absent-theme-quantum-01":
        "Synthesise what our corpus covers on quantum machine learning — the main "
        "ideas, how they connect, and where the gaps are.",
    "mp-poisoned-analysis-privacy-01":
        "Synthesise what the course covers on privacy in machine learning — the "
        "attack types, the defenses, and the privacy–utility tradeoff — and how "
        "these ideas interact.",
    "ap-comp599-tech-debt-article-01":
        "Synthesise what our corpus says about hidden technical debt in ML systems "
        "— the kinds of debt and how they interrelate.",
    "rp-comp599-fairness-research-01":
        "Synthesise what the corpus covers on fairness in ML and how it connects to "
        "privacy and explainability.",
}
_SOURCES_TURN = {"id": "sx_sources", "examiner_goal": "sharpen",
    "user_template": "Which exact lecture sources and wiki pages did this synthesis draw on? "
                     "List them with precise locators."}
# Judgment-deferring accept — never forces a page (CE decides per its native trigger).
_CRYSTALLIZE_TURN = {"id": "sx_crystallize", "examiner_goal": "crystallize_accept",
    "user_template": "If that synthesis is substantial enough to stand as its own analysis "
                     "page, please file it as one now, citing those exact sources. If it is "
                     "really just a simple lookup, no need."}
_OFFLEASH_TURN = {"id": "sx_offleash", "examiner_goal": "gap_stress",
    "user_template": (
        "Now go beyond what is strictly in our corpus: using your own reasoning and "
        "background knowledge, propose (a) additional sources or datasets worth "
        "acquiring, (b) open questions this raises, and (c) hypotheses worth testing "
        "to sharpen this work. Clearly flag which points rely on your own knowledge "
        "versus our corpus, and stay cautious where you are unsure.")}


def _unit_scenario(scen: dict[str, Any], arm: str) -> dict[str, Any]:
    """Same topic/gold/fixtures, but turns = synthesis query → sources →
    (CE only) native crystallize → off-leash."""
    s = copy.deepcopy(scen)
    sid = s.get("id")
    synth = {"id": "t1", "examiner_goal": "open_brief", "user_template": SYNTH_QUERIES[sid]}
    turns = [synth, copy.deepcopy(_SOURCES_TURN)]
    if arm == "ce_product_e2e_v1":
        turns.append(copy.deepcopy(_CRYSTALLIZE_TURN))
        s["allow_crystallization"] = True
    else:
        s["allow_crystallization"] = False
    turns.append(copy.deepcopy(_OFFLEASH_TURN))
    s["turns"] = turns
    return s


def _preflight_rag(index_dir: Path) -> None:
    import numpy, fastembed  # noqa: F401
    from bench.agentic_query_bench.rag_modern import ModernRagIndex, rag_search
    idx = ModernRagIndex.load(index_dir)
    assert rag_search(idx, "machine learning", mode="hybrid", rerank=False,
                      no_answer_threshold=0.685).hits, "rag preflight empty"


def run_stage1(*, frozen_ws: Path, out_dir: Path, calibration: dict[str, Any],
               index_dir: Path, models=MODELS, only=None, log=print) -> dict[str, Any]:
    out_dir = Path(out_dir)
    units = out_dir / "units"; units.mkdir(parents=True, exist_ok=True)
    work = out_dir / "work"; work.mkdir(parents=True, exist_ok=True)
    skill_dir = PA.product_skill_dir()
    _preflight_rag(index_dir)
    log("[preflight] rag ok", flush=True)
    done, failed = [], []

    for model in models:
        for sid in SCORED:
            scen = json.loads((ROOT / "scenarios" / f"{sid}.json").read_text())
            doss_p = ROOT / "evidence_dossiers" / f"{sid}.json"
            doss = json.loads(doss_p.read_text()) if doss_p.is_file() else None
            for arm in ARMS:
                if only and (model, sid, arm) not in only:
                    continue
                cp = units / f"{model}-{sid}-{arm}.json"
                if cp.is_file() and not (json.loads(cp.read_text()).get("trajectory") or {}).get("hard_error"):
                    done.append(cp.name); continue
                uscen = _unit_scenario(scen, arm)
                is_ce = arm == "ce_product_e2e_v1"
                log(f"[unit] {model} {sid} {arm} …", flush=True)
                traj = run_product_trajectory(uscen, arm, frozen_ws=frozen_ws, model=model,
                    work_dir=work, repeat="sec", calibration=calibration,
                    frozen_index_dir=index_dir, skill_dir=skill_dir, max_agent_turns=14,
                    keep_snapshot=is_ce)
                mech = product_mechanics.audit(traj, uscen, dossier=doss)
                turns = traj.get("turns") or []
                synthesis_reply = turns[0].get("assistant", "") if turns else ""
                offleash_answer = turns[-1].get("assistant", "") if turns else ""
                # native offer = a crystallize offer appearing BEFORE the accept turn (idx 2)
                native_offer = any(
                    _CRYSTALLIZE_OFFER.search(t.get("assistant", "") or "")
                    for t in turns[:2]) if is_ce else None
                page_body, page_path = "", None
                created = mech.get("crystallization_pages_created") or []
                snap = traj.get("snapshot")
                if is_ce and created and snap:
                    p = Path(snap) / created[0]
                    if p.is_file():
                        page_body = p.read_text(encoding="utf-8", errors="replace"); page_path = created[0]
                rec = {"model": model, "scenario_id": sid, "arm": arm, "is_synthesis_query": True,
                       "synthesis_reply": synthesis_reply, "offleash_answer": offleash_answer,
                       "native_crystallization_offer": native_offer,
                       "page_authored": bool(page_body), "page_path": page_path, "page_body": page_body,
                       "crystallization_committed": mech.get("crystallization_committed") if is_ce else None,
                       "rag_retrieval_calls": mech.get("rag_retrieval_calls"),
                       "retrieval_failure": mech.get("retrieval_failure"),
                       "mechanics": mech, "trajectory": traj}
                cp.write_text(json.dumps(rec, indent=2), encoding="utf-8")
                if snap:
                    PA.force_rmtree(Path(snap))
                rag_ok = not (arm == "rag_modern_agentic_v1" and mech.get("retrieval_failure"))
                ok = bool(synthesis_reply) and bool(offleash_answer) and rag_ok and not traj.get("model_drift")
                log(f"   synth={len(synthesis_reply)} offleash={len(offleash_answer)} "
                    f"native_offer={native_offer} page={bool(page_body)}({len(page_body)}) "
                    f"rag_calls={mech.get('rag_retrieval_calls')} drift={traj.get('model_drift')}", flush=True)
                (done if ok else failed).append(cp.name)

    status = {"done": done, "failed": failed,
              "n_pages": sum(1 for f in (units).glob("*ce_product*.json")
                             if json.loads(Path(f).read_text()).get("page_authored"))}
    (out_dir / "stage1-status.json").write_text(json.dumps(status, indent=2), encoding="utf-8")
    log(f"[stage1] done={len(done)} failed={len(failed)} native_pages={status['n_pages']}", flush=True)
    return status


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=Path, default=Path("~/.cache/sy-phase2-bench/ws").expanduser())
    ap.add_argument("--out-dir", type=Path, default=ROOT.parents[1] / "bench/results/product-secondary-v1")
    ap.add_argument("--calibration", type=Path,
                    default=ROOT.parents[1] / "bench/results/rag-modern-calibration/calibration.json")
    ap.add_argument("--index-dir", type=Path, default=ROOT.parents[1] / "bench/results/rag-modern-index")
    ap.add_argument("--models", default=",".join(MODELS))
    args = ap.parse_args(argv)
    cal = json.loads(args.calibration.read_text())
    run_stage1(frozen_ws=args.workspace.expanduser().resolve(), out_dir=args.out_dir,
               calibration=cal, index_dir=args.index_dir,
               models=[m for m in args.models.split(",") if m])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
