"""Secondary analysis — Stage 2: 4-judge blind pass on the synthesis replies +
a judge self-preference t-test.

Judges: xai/grok-4.5 + openai/gpt-5.5 (non-Claude) + anthropic/claude-opus-4-8 +
anthropic/claude-opus-5 (Claude — the generator family, included ON PURPOSE here to
MEASURE self-preference, which the frozen primary correctly excluded).

- Reply-vs-reply is arm-blindable → scored, per-arm dimension means.
- Self-preference test: every answer is Claude-authored, so per answer we compare
  mean(Claude-judge score) vs mean(non-Claude-judge score); a paired t-test on the
  difference. Run only if n is sufficient; else report descriptively.
Page-vs-reply stays descriptive (unblindable) — handled in the interim read.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from bench.agentic_query_bench.judges import build_judge_prompt, parse_judgment
from bench.agentic_query_bench.llm_util import robust_llm_call
from bench.agentic_query_bench.product_judge import _scrub, build_product_pack
from bench.agentic_query_bench.product_secondary import SYNTH_QUERIES
from bench.agentic_query_bench.scoring import load_charter

ROOT = Path(__file__).resolve().parent
DEFAULT_UNITS = ROOT.parents[1] / "bench/results/product-secondary-v1/units"
SALT = "ce-secondary-selfpref-2026-08-02"

# judge label → (provider, model). Claude judges included to test self-preference.
JUDGES = {
    "xai": ("xai", None),
    "openai": ("openai", "gpt-5.5"),
    # Claude judges via the claude-code SUBSCRIPTION (the anthropic HTTP API ran out
    # of credits mid-run, 2026-08-02); the subscription serves both opus versions.
    "claude-opus-4-8": ("claude-code", "claude-opus-4-8"),
    "claude-opus-5": ("claude-code", "claude-opus-5"),
}
CLAUDE_JUDGES = {"claude-opus-4-8", "claude-opus-5"}


def _code(model: str, sid: str, arm: str) -> str:
    return "s" + hashlib.sha1(f"{model}|{sid}|{arm}|{SALT}".encode()).hexdigest()[:11]


def _mini_traj(unit: dict) -> dict:
    """A one-turn trajectory carrying the synthesis reply, for build_product_pack."""
    sid = unit["scenario_id"]
    return {"scenario_id": sid, "arm": unit["arm"], "model": unit["model"],
            "turns": [{"turn_id": "t1", "user": SYNTH_QUERIES.get(sid, ""),
                       "assistant": unit.get("synthesis_reply", ""), "tool_uses": []}],
            "cite_resolver": (unit.get("trajectory") or {}).get("cite_resolver") or {}}


def build_packs(out_dir: Path, units_dir: Path = DEFAULT_UNITS, log=print) -> int:
    out_dir = Path(out_dir); pk = out_dir / "packs"; pk.mkdir(parents=True, exist_ok=True)
    sealed = {}
    n = 0
    for f in sorted(Path(units_dir).glob("*.json")):
        u = json.loads(f.read_text())
        if not (u.get("synthesis_reply") or "").strip():
            continue  # skip limit-blocked/empty
        code = _code(u["model"], u["scenario_id"], u["arm"])
        scen = json.loads((ROOT / "scenarios" / f"{u['scenario_id']}.json").read_text())
        doss_p = ROOT / "evidence_dossiers" / f"{u['scenario_id']}.json"
        doss = json.loads(doss_p.read_text()) if doss_p.is_file() else None
        traj = _mini_traj(u)
        pack = build_product_pack(scen, traj, doss, code)
        # extra arm-blinding scrub over the reply text (build_product_pack already scrubs)
        for t in pack["trajectory"]["turns"]:
            t["assistant"] = _scrub(t["assistant"])
        (pk / f"{code}.json").write_text(json.dumps(pack, indent=1, ensure_ascii=False), encoding="utf-8")
        sealed[code] = {"model": u["model"], "scenario_id": u["scenario_id"], "arm": u["arm"]}
        n += 1
    (out_dir / "sealed.json").write_text(json.dumps(sealed, indent=1), encoding="utf-8")
    log(f"[build] {n} reply packs")
    return n


def run_judges(out_dir: Path, max_workers: int = 5, log=print) -> dict:
    """Concurrent 4-judge pass (HTTP calls, no CLI-hang risk). Resumable."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    out_dir = Path(out_dir); jd = out_dir / "judgments"; jd.mkdir(parents=True, exist_ok=True)
    packs = sorted((out_dir / "packs").glob("*.json"))
    tasks = []
    for p in packs:
        pack = json.loads(p.read_text())
        applicable = (pack.get("scenario") or {}).get("applicable_dimensions") or {}
        prompt = build_judge_prompt(pack)
        for label, (provider, model) in JUDGES.items():
            out = jd / f"{p.stem}.{label}.json"
            if not out.is_file():
                tasks.append((label, provider, model, prompt, applicable, out))

    def _one(task) -> bool:
        label, provider, model, prompt, applicable, out = task
        pr = prompt
        for _ in range(2):
            try:
                text = robust_llm_call(provider, pr, model=model, max_tokens=3000,
                                       limit_sleep_s=300, limit_patience_h=2.0, log=lambda *a: None)
            except Exception:  # noqa: BLE001
                return False
            parsed = parse_judgment(text, applicable_dimensions=applicable)
            if parsed:
                parsed["judge"] = label
                out.write_text(json.dumps(parsed, indent=1), encoding="utf-8")
                return True
            pr = prompt + "\n\nREMINDER: STRICT JSON only."
        return False

    done = fail = 0
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        for fut in as_completed([ex.submit(_one, t) for t in tasks]):
            if fut.result():
                done += 1
            else:
                fail += 1
    total = len(packs) * len(JUDGES)
    have = len(list(jd.glob("*.json")))
    log(f"[judges] {have}/{total} present ({done} new, {fail} failed)")
    return {"present": have, "expected": total, "failed": fail}


def _mean(xs): return sum(xs) / len(xs) if xs else None
def _sd(xs):
    if len(xs) < 2: return None
    m = _mean(xs); return (sum((x - m) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5


def analyze(out_dir: Path, log=print) -> dict:
    out_dir = Path(out_dir)
    sealed = json.loads((out_dir / "sealed.json").read_text())
    charter = load_charter(); dims = set((charter.get("dimensions") or {}).keys())
    # code -> judge -> mean score (over that judge's dimension scores for the answer)
    jscore = defaultdict(dict)
    for jf in (out_dir / "judgments").glob("*.json"):
        code, _, judge = jf.name[:-5].partition(".")
        sc = (json.loads(jf.read_text()).get("scores") or {})
        vals = [v for k, v in sc.items() if k in dims]
        if vals:
            jscore[code][judge] = _mean(vals)
    # self-preference: per answer with all 4 judges, claude-mean vs nonclaude-mean
    diffs = []
    rows = []
    for code, js in jscore.items():
        if not all(j in js for j in JUDGES):
            continue
        cl = _mean([js[j] for j in CLAUDE_JUDGES])
        ncl = _mean([js[j] for j in JUDGES if j not in CLAUDE_JUDGES])
        diffs.append(cl - ncl)
        rows.append({**sealed.get(code, {}), "claude_judge_mean": round(cl, 3),
                     "nonclaude_judge_mean": round(ncl, 3), "diff": round(cl - ncl, 3)})
    n = len(diffs)
    t = df = p = None
    if n >= 2:
        md, sd = _mean(diffs), _sd(diffs)
        if sd and sd > 0:
            t = md / (sd / (n ** 0.5)); df = n - 1
            try:
                from scipy import stats  # type: ignore
                p = float(2 * stats.t.sf(abs(t), df))
            except Exception:  # noqa: BLE001
                p = None
    # per-judge overall mean (bias direction) + per-arm dimension means
    judge_overall = {j: round(_mean([js[j] for js in jscore.values() if j in js]) or 0, 3) for j in JUDGES}
    per_arm = defaultdict(list)
    for code, js in jscore.items():
        arm = sealed.get(code, {}).get("arm")
        per_arm[arm].append(_mean(list(js.values())))
    arm_means = {a: round(_mean(v), 3) for a, v in per_arm.items() if v}
    report = {
        "n_answers_all4": n, "judge_overall_mean": judge_overall,
        "self_preference": {
            "mean_claude_minus_nonclaude": round(_mean(diffs), 4) if diffs else None,
            "sd": round(_sd(diffs), 4) if _sd(diffs) else None,
            "t_stat": round(t, 3) if t is not None else None, "df": df, "p_value": p,
            "sufficiently_powered": (n >= 15),
            "reading": ("Claude judges score Claude-authored answers HIGHER" if (t and t > 2)
                        else "no significant self-preference at this n" if t is not None else "underpowered"),
        },
        "arm_means_pooled": arm_means, "rows": rows,
    }
    (out_dir / "selfpref-analysis.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    log(f"[analyze] n={n} claude-nonclaude Δ={report['self_preference']['mean_claude_minus_nonclaude']} "
        f"t={report['self_preference']['t_stat']} p={p}")
    return report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "run", "analyze", "all"])
    ap.add_argument("--out-dir", type=Path, default=ROOT.parents[1] / "bench/results/product-secondary-judge")
    ap.add_argument("--units-dir", type=Path, default=DEFAULT_UNITS,
                    help="Stage-1 unit JSON directory (used by build/all)")
    a = ap.parse_args(argv)
    if a.cmd in ("build", "all"): build_packs(a.out_dir, units_dir=a.units_dir)
    if a.cmd in ("run", "all"): run_judges(a.out_dir)
    if a.cmd in ("analyze", "all"): print(json.dumps(analyze(a.out_dir), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
