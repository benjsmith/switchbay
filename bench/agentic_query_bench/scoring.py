"""Primary score = mean of 5 cluster means (judgment-charter.json canonical)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_CHARTER_PATH = Path(__file__).resolve().parent / "judgment-charter.json"


def load_charter(path: Path | None = None) -> dict[str, Any]:
    p = path or _CHARTER_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def cluster_scores(
    dim_scores: dict[str, float | None],
    charter: dict[str, Any] | None = None,
    *,
    resteer_rate: float | None = None,
) -> dict[str, float]:
    """Compute five cluster scores from diagnostic dimensions.

    unproductive_drift: the mechanical resteer_rate is the PRIMARY signal
    (charter); the judge value only ADDS drift the script missed (borderline
    unlabeled spans), so when both exist we take max(mechanical, judge) —
    a judge can never lower the mechanical floor.
    """
    ch = charter or load_charter()
    scores = dict(dim_scores)
    if resteer_rate is not None:
        jv = scores.get("unproductive_drift")
        mech = float(resteer_rate)
        scores["unproductive_drift"] = mech if jv is None else max(mech, float(jv))
    if scores.get("unproductive_drift") is not None:
        scores["unproductive_drift_inverted"] = 1.0 - float(scores["unproductive_drift"])

    out: dict[str, float] = {}
    for name, meta in (ch.get("clusters") or {}).items():
        dims = meta.get("dims") or []
        vals: list[float] = []
        for d in dims:
            v = scores.get(d)
            if v is None:
                continue
            vals.append(float(v))
        m = _mean(vals)
        if m is not None:
            out[name] = m
    return out


def primary_score(
    dim_scores: dict[str, float | None],
    charter: dict[str, Any] | None = None,
    *,
    resteer_rate: float | None = None,
    drop_judge_drift: bool = False,
) -> dict[str, Any]:
    ch = charter or load_charter()
    scores = dict(dim_scores)
    if drop_judge_drift:
        # keep mechanical resteer only
        if resteer_rate is not None:
            scores["unproductive_drift"] = float(resteer_rate)
        scores.pop("serendipity_quality", None)

    clusters = cluster_scores(scores, ch, resteer_rate=resteer_rate)
    order = (ch.get("primary_score") or {}).get("clusters") or list(clusters)
    vals = [clusters[c] for c in order if c in clusters]
    primary = _mean(vals)
    return {
        "cluster_scores": clusters,
        "primary_score": primary,
        "diagnostic": {k: scores.get(k) for k in (ch.get("dimensions") or {})},
        "serendipity_quality": scores.get("serendipity_quality"),
        "task_usefulness": scores.get("task_usefulness"),
    }


def mechanical_resteer_rate(turns: list[dict[str, Any]]) -> float:
    if not turns:
        return 0.0
    n = sum(1 for t in turns if t.get("examiner_branch") == "resteer"
            or t.get("branch_used") == "resteer"
            or t.get("is_resteer"))
    return n / len(turns)


def apply_provenance_gate(
    result: dict[str, Any],
    *,
    provenance_violation: bool,
) -> dict[str, Any]:
    out = dict(result)
    out["provenance_violation"] = bool(provenance_violation)
    out["in_headline_primary"] = not bool(provenance_violation)
    return out
