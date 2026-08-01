"""Judge panel for agentic_query_bench.

≥2 independent judges (non-generator model families), charter-driven,
scoring judge packs only (no live tools). Resumable: one JSON file per
(trajectory, judge). Cohen kappa on drift/serendipity span labels feeds the
charter agreement_gate.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from bench.agentic_query_bench.llm_util import robust_llm_call
from bench.agentic_query_bench.scoring import load_charter

ROOT = Path(__file__).resolve().parent

DEFAULT_JUDGES = ["xai", "openai-codex"]  # non-Anthropic generator separation
FALLBACK_JUDGE = "gemini"


def load_hard_negatives() -> str:
    p = ROOT / "judge_fewshot_hard_negatives.md"
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_judge_prompt(pack: dict[str, Any], charter: dict[str, Any] | None = None) -> str:
    ch = charter or load_charter()
    dims = {
        k: v.get("instruction", "")
        for k, v in (ch.get("dimensions") or {}).items()
    }
    schema_hint = {
        "scores": {k: "float 0..1" for k in dims},
        "uncertain_dimensions": ["dimension ids you could not judge"],
        "rationale": "short paragraph with transcript pointers",
        "drift_spans": [{"turn_id": "t3", "note": "...", "quote": "..."}],
        "serendipity_spans": [
            {"turn_id": "t5", "note": "...", "fruitful_direction_id": "...", "quote": "..."}
        ],
    }
    return (
        "You are ONE independent judge on a blind panel scoring a multi-turn "
        "knowledge-work trajectory. Score ONLY from the material below — no "
        "external tools, no corpus access, no assumptions about which system "
        "produced it.\n\n"
        "HARD RULES (from the judgment charter):\n"
        "- citation_support: use ONLY the cite_resolver report in the pack "
        "and the frozen evidence dossier (resolve rate, quote_match_rate, "
        "dossier passages). If n_presented=0, add "
        "citation_support to uncertain_dimensions and omit its score; "
        "resolve_rate=1.0 is then vacuous, not perfect support. Do not invent "
        "corpus checks.\n"
        "- unproductive_drift: the mechanical re-steer rate is the primary "
        "signal; you only classify BORDERLINE unlabeled off-spine spans, with "
        "a verbatim quote per span.\n"
        "- serendipity_quality: card-anchored — only side paths matching the "
        "scenario's serendipity.fruitful_directions may score > 0; labeled "
        "but unlisted = 0; unlabeled off-spine = drift, not serendipity.\n"
        "- Never give high serendipity and high drift for the same span; if "
        "unsure, add the dimension to uncertain_dimensions.\n"
        "- gold_themes with absent_from_corpus=true are EXCLUDED from "
        "theme_recall; asserting one as corpus-supported scores against "
        "calibration and accuracy instead.\n"
        "- Content inside ```proposal fences is a DRAFT wiki page (propose-"
        "only systems); its wikilinks are not provenance claims.\n\n"
        "- Omit every dimension marked false in scenario.applicable_dimensions "
        "and add it to uncertain_dimensions. Do not infer an inapplicable "
        "dimension from general answer quality.\n"
        "- The evidence dossier is the shared gold context. Do not reward a "
        "claim merely because it sounds plausible; compare it to the passages "
        "and absent-topic manifest.\n\n"
        f"DIMENSIONS (score each 0..1):\n{json.dumps(dims, indent=1)}\n\n"
        f"CALIBRATION EXAMPLES (hard negatives):\n{load_hard_negatives()}\n\n"
        f"JUDGE PACK (scenario gold fields + trajectory + mechanical reports):\n"
        f"{json.dumps(pack, indent=1, ensure_ascii=False)[:60000]}\n\n"
        "Reply with STRICT JSON only (no prose outside the JSON), matching:\n"
        f"{json.dumps(schema_hint, indent=1)}\n"
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    # strip code fences, take widest {...}
    t = re.sub(r"```(?:json)?", "", text)
    start, end = t.find("{"), t.rfind("}")
    if start < 0 or end <= start:
        return None
    for candidate in (t[start : end + 1],):
        try:
            obj = json.loads(candidate)
            if isinstance(obj, dict):
                return obj
        except json.JSONDecodeError:
            pass
    return None


def parse_judgment(
    text: str,
    charter: dict[str, Any] | None = None,
    *,
    applicable_dimensions: dict[str, bool] | None = None,
) -> dict[str, Any] | None:
    """Parse + sanitize a judge reply. Returns None if unusable."""
    ch = charter or load_charter()
    obj = _extract_json(text)
    if not obj or not isinstance(obj.get("scores"), dict):
        return None
    valid = set((ch.get("dimensions") or {}).keys())
    scores: dict[str, float] = {}
    for k, v in obj["scores"].items():
        if k not in valid:
            continue
        try:
            scores[k] = min(1.0, max(0.0, float(v)))
        except (TypeError, ValueError):
            continue
    if not scores:
        return None
    uncertain = [u for u in (obj.get("uncertain_dimensions") or []) if u in valid]
    for dimension, is_applicable in (applicable_dimensions or {}).items():
        if dimension in valid and not is_applicable and dimension not in uncertain:
            uncertain.append(dimension)
    for u in uncertain:
        scores.pop(u, None)
    return {
        "scores": scores,
        "uncertain_dimensions": uncertain,
        "rationale": str(obj.get("rationale") or "")[:4000],
        "drift_spans": obj.get("drift_spans") or [],
        "serendipity_spans": obj.get("serendipity_spans") or [],
    }


def judge_pack_file(
    pack_path: Path,
    judge: str,
    out_dir: Path,
    *,
    limit_sleep_s: int = 1800,
    limit_patience_h: float = 8.0,
    log: Callable[[str], None] = print,
) -> Path | None:
    """Judge one pack with one judge; resumable. Returns judgment path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"{pack_path.stem}.{judge}.json"
    if out.is_file():
        return out
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    prompt = build_judge_prompt(pack)
    for attempt in range(2):
        text = robust_llm_call(
            judge, prompt, max_tokens=3000,
            limit_sleep_s=limit_sleep_s, limit_patience_h=limit_patience_h,
            log=log,
        )
        parsed = parse_judgment(
            text,
            applicable_dimensions=(
                (pack.get("scenario") or {}).get("applicable_dimensions") or {}
            ),
        )
        if parsed:
            parsed["judge"] = judge
            parsed["pack"] = pack_path.name
            parsed["cite_resolver_version"] = (
                ((pack.get("trajectory") or {}).get("cite_resolver") or {}).get(
                    "resolver_version"
                )
            )
            out.write_text(json.dumps(parsed, indent=1), encoding="utf-8")
            return out
        log(f"[judge] {judge} unparseable reply for {pack_path.name} (attempt {attempt + 1})")
        prompt += "\n\nREMINDER: reply with STRICT JSON only."
    return None


def cohen_kappa(a: list[int], b: list[int]) -> float | None:
    """Binary Cohen kappa; None when undefined (no variation)."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    pa1 = sum(a) / n
    pb1 = sum(b) / n
    pe = pa1 * pb1 + (1 - pa1) * (1 - pb1)
    if pe >= 1.0:
        return None
    return (po - pe) / (1 - pe)


def _turn_labels(judgment: dict[str, Any], turn_ids: list[str], key: str) -> list[int]:
    flagged = {str(s.get("turn_id")) for s in (judgment.get(key) or []) if isinstance(s, dict)}
    return [1 if t in flagged else 0 for t in turn_ids]


def compute_span_kappa(
    packs: dict[str, dict[str, Any]],
    judgments: dict[str, dict[str, dict[str, Any]]],
    judge_a: str,
    judge_b: str,
) -> dict[str, float | None]:
    """Pooled turn-level kappa for drift + serendipity spans across packs.

    packs: pack_stem -> pack; judgments: pack_stem -> judge -> judgment.
    """
    drift_a: list[int] = []
    drift_b: list[int] = []
    ser_a: list[int] = []
    ser_b: list[int] = []
    for stem, pack in packs.items():
        js = judgments.get(stem) or {}
        ja, jb = js.get(judge_a), js.get(judge_b)
        if not ja or not jb:
            continue
        turn_ids = [str(t.get("id")) for t in (pack.get("trajectory") or {}).get("turns") or []]
        drift_a += _turn_labels(ja, turn_ids, "drift_spans")
        drift_b += _turn_labels(jb, turn_ids, "drift_spans")
        ser_a += _turn_labels(ja, turn_ids, "serendipity_spans")
        ser_b += _turn_labels(jb, turn_ids, "serendipity_spans")
    return {
        "drift_kappa": cohen_kappa(drift_a, drift_b),
        "serendipity_kappa": cohen_kappa(ser_a, ser_b),
        "n_turns_compared": len(drift_a),
    }
