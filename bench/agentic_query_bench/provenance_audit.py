"""Retrospective provenance audit for the frozen agentic-query pilot.

The scored report remains immutable.  This module classifies the resolver's
unresolved citation tokens and computes sensitivity views under progressively
narrower meanings of "provenance violation":

* strict_syntax: the frozen charter's one-unresolved-token trajectory gate;
* conservative_semantic: nonexistent paths and unresolved semantic wikilinks;
* clear_fabrication: only a fully specified, nonexistent provenance path.

The classification is deterministic and uses the frozen workspace inventory.
It does not regenerate answers, re-run judges, or edit trajectory checkpoints.
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bench.agentic_query_bench.aggregate import (
    _mean,
    _sd,
    load_results,
    paired_bootstrap,
)

AUDIT_SCHEMA_VERSION = 1

STRICT = "strict_syntax"
CONSERVATIVE = "conservative_semantic"
CLEAR = "clear_fabrication"
REGIMES = (STRICT, CONSERVATIVE, CLEAR)

_ELLIPSIS_RE = re.compile(r"(?:\.\.\.|…)")
_LOCUS_RE = re.compile(r"\blb2-\d+\b", re.IGNORECASE)
_FILE_PREFIX_RE = re.compile(
    r"^(.*\.(?:extracted\.md|md|txt|rst|json|yaml|yml|html|pdf|csv|xlsx|pptx))"
)
_GENERIC_LINK_TARGETS = {
    "concept",
    "entity",
    "fact",
    "source",
    "wikilink",
    "wikilinks",
    "page",
    "stem",
}


def _workspace_inventory(workspace: Path) -> set[str]:
    rels: set[str] = set()
    if not workspace.is_dir():
        return rels
    for path in workspace.rglob("*"):
        if path.is_file():
            try:
                rels.add(path.relative_to(workspace).as_posix())
            except ValueError:
                continue
    return rels


def _normalise_vault_path(target: str) -> str:
    value = target.strip().strip("`\"'")
    if value.startswith("vault:"):
        value = value[len("vault:") :].strip()
    if value.startswith("vault/"):
        return value
    return f"vault/{value}"


def _inventory_has_path(inventory: set[str], target: str) -> bool:
    if target in inventory:
        return True
    if target.startswith("wiki/"):
        return False
    return _normalise_vault_path(target) in inventory


def _unique_locus_match(inventory: set[str], target: str) -> str | None:
    match = _LOCUS_RE.search(target)
    if not match:
        return None
    locus = match.group(0).casefold()
    logical = {
        rel.removesuffix(".extracted.md")
        for rel in inventory
        if rel.startswith("vault/") and locus in rel.casefold()
    }
    if len(logical) != 1:
        return None
    key = next(iter(logical))
    candidates = sorted(rel for rel in inventory if rel.removesuffix(".extracted.md") == key)
    return candidates[-1] if candidates else None


def _unique_source_stem_match(inventory: set[str], target: str) -> str | None:
    candidate = _normalise_vault_path(target)
    logical = {
        rel.removesuffix(".extracted.md")
        for rel in inventory
        if rel.startswith("vault/")
        and (
            rel.startswith(candidate)
            or rel.removesuffix(".extracted.md").startswith(candidate)
        )
    }
    if len(logical) != 1:
        return None
    key = next(iter(logical))
    matches = sorted(rel for rel in inventory if rel.removesuffix(".extracted.md") == key)
    return matches[-1] if matches else None


def classify_unresolved(
    cite: dict[str, Any],
    inventory: set[str],
) -> dict[str, Any]:
    """Classify one unresolved, presented, gate-eligible citation token."""
    raw = str(cite.get("raw") or "")
    target = str(cite.get("target") or "").strip()
    kind = str(cite.get("kind") or "")
    note = str(cite.get("note") or "")
    category: str
    rationale: str
    identifiable_as: str | None = None

    if kind == "wikilink":
        target_cf = target.casefold()
        if (
            target_cf in _GENERIC_LINK_TARGETS
            or _ELLIPSIS_RE.search(target)
            or not target
        ):
            category = "draft_or_template_placeholder"
            rationale = "Generic or visibly abbreviated draft wikilink, not a concrete source path."
        else:
            category = "unresolved_semantic_wikilink"
            rationale = (
                "Concrete wikilink target has no page in the frozen workspace; "
                "it may be a proposed link or an implied existing page."
            )
    elif kind == "wiki_path":
        category = "nonexistent_full_path"
        rationale = "Fully specified wiki path does not exist in the frozen workspace."
    elif kind == "vault":
        compound = (
            " vs " in target.casefold()
            or " vault:" in target.casefold()
            or " × " in target
            or " + " in target
            or " / " in target
        )
        if compound:
            category = "compound_or_annotated_locator"
            rationale = "Multiple locators or prose were combined inside one vault citation target."
        elif _ELLIPSIS_RE.search(target):
            category = "abbreviated_locator"
            rationale = "Citation uses an ellipsis shorthand rather than a resolvable identifier."
            identifiable_as = _unique_locus_match(inventory, target)
        else:
            prefix_match = _FILE_PREFIX_RE.match(target)
            prefix = prefix_match.group(1) if prefix_match else ""
            if prefix and _inventory_has_path(inventory, prefix) and prefix != target:
                category = "embedded_real_path_with_annotation"
                identifiable_as = (
                    prefix if prefix.startswith("wiki/") else _normalise_vault_path(prefix)
                )
                rationale = (
                    "Target begins with a real exact path, but trailing prose was parsed "
                    "as part of the filename."
                )
            else:
                identifiable_as = _unique_source_stem_match(inventory, target)
                if identifiable_as:
                    category = "identifiable_source_stem"
                    rationale = (
                        "Citation omits a suffix or otherwise names a unique frozen "
                        "logical source without using its exact path."
                    )
                else:
                    identifiable_as = _unique_locus_match(inventory, target)
                    if identifiable_as:
                        category = "identifiable_locus_near_miss"
                        rationale = (
                            "Malformed or mistimestamped locator still uniquely identifies "
                            "one LectureBank source family."
                        )
                    elif _FILE_PREFIX_RE.fullmatch(target):
                        category = "nonexistent_full_path"
                        rationale = (
                            "Fully specified vault path does not exist and cannot be "
                            "uniquely reconciled to a frozen source."
                        )
                    else:
                        category = "malformed_locator"
                        rationale = "Citation payload is neither a resolvable path nor a unique locator."
    else:
        category = "nonexistent_full_path"
        rationale = "Concrete provenance locator did not resolve."

    gates = {
        STRICT: True,
        CONSERVATIVE: category in {
            "nonexistent_full_path",
            "unresolved_semantic_wikilink",
        },
        CLEAR: category == "nonexistent_full_path",
    }
    return {
        "category": category,
        "rationale": rationale,
        "identifiable_as": identifiable_as,
        "gates": gates,
        "raw": raw,
        "target": target,
        "kind": kind,
        "resolver_note": note,
    }


def _line_context(text: str, raw: str, limit: int = 500) -> str:
    for line in text.splitlines():
        if raw and raw in line:
            return line.strip()[:limit]
    return ""


def collect_items(
    trajectories: list[dict[str, Any]],
    inventory: set[str],
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for trajectory in trajectories:
        turns = {
            str(turn.get("id")): turn
            for turn in (trajectory.get("turns") or [])
        }
        resolver = trajectory.get("cite_resolver") or {}
        for per_turn in resolver.get("per_turn") or []:
            turn_id = str(per_turn.get("turn_id") or "")
            turn = turns.get(turn_id) or {}
            for cite in ((per_turn.get("report") or {}).get("cites") or []):
                if (
                    cite.get("resolves")
                    or not cite.get("presented_as_citation")
                    or not cite.get("gate_eligible", True)
                ):
                    continue
                classified = classify_unresolved(cite, inventory)
                items.append({
                    "stem": trajectory.get("_stem"),
                    "scenario": trajectory.get("scenario_id"),
                    "family": trajectory.get("family"),
                    "arm": trajectory.get("arm"),
                    "seed": trajectory.get("seed_tag"),
                    "turn": turn_id,
                    "line_context": _line_context(
                        str(turn.get("assistant") or ""),
                        str(cite.get("raw") or ""),
                    ),
                    **classified,
                })
    return items


def _regime_gate_by_stem(items: list[dict[str, Any]], regime: str) -> dict[str, bool]:
    gate: dict[str, bool] = defaultdict(bool)
    for item in items:
        gate[str(item["stem"])] |= bool((item.get("gates") or {}).get(regime))
    return dict(gate)


def _sensitivity(
    frozen_rows: list[dict[str, Any]],
    items: list[dict[str, Any]],
) -> dict[str, Any]:
    output: dict[str, Any] = {}
    arms = sorted({str(row.get("arm")) for row in frozen_rows})
    for regime in REGIMES:
        gate = _regime_gate_by_stem(items, regime)
        included = [
            row for row in frozen_rows
            if row.get("completion")
            and row.get("primary") is not None
            and not gate.get(str(row.get("stem")), False)
        ]
        per_arm: dict[str, Any] = {}
        scenario_means: dict[str, dict[str, float]] = defaultdict(dict)
        for arm in arms:
            all_arm = [row for row in frozen_rows if row.get("arm") == arm]
            kept = [row for row in included if row.get("arm") == arm]
            values = [float(row["primary"]) for row in kept]
            grouped: dict[str, list[float]] = defaultdict(list)
            for row in kept:
                grouped[str(row.get("scenario"))].append(float(row["primary"]))
            for scenario, scores in grouped.items():
                scenario_means[arm][scenario] = sum(scores) / len(scores)
            per_arm[arm] = {
                "n_total": len(all_arm),
                "n_included": len(kept),
                "n_gated": len(all_arm) - len(kept),
                "primary_mean": _mean(values),
                "primary_sd": _sd(values),
            }
        tests: dict[str, Any] = {}
        if "ce_query" in scenario_means:
            for arm in arms:
                if arm == "ce_query":
                    continue
                result = paired_bootstrap(
                    scenario_means["ce_query"],
                    scenario_means.get(arm, {}),
                )
                if result:
                    tests[f"ce_query_vs_{arm}"] = result
        output[regime] = {
            "per_arm": per_arm,
            "paired_bootstrap_primary": tests,
        }
    return output


def build_audit(results_dir: Path, workspace: Path) -> dict[str, Any]:
    trajectories, _packs, _judgments = load_results(results_dir)
    frozen_report_path = results_dir / "report.json"
    frozen_report = json.loads(frozen_report_path.read_text(encoding="utf-8"))
    inventory = _workspace_inventory(workspace)
    items = collect_items(trajectories, inventory)

    category_counts = Counter(str(item["category"]) for item in items)
    arm_category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for item in items:
        arm_category_counts[str(item["arm"])][str(item["category"])] += 1

    strict_from_items = _regime_gate_by_stem(items, STRICT)
    frozen_gated = {
        str(row["stem"])
        for row in frozen_report.get("rows") or []
        if row.get("provenance_violation")
    }
    derived_gated = {stem for stem, gated in strict_from_items.items() if gated}

    return {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "created_utc": datetime.now(timezone.utc).isoformat(),
        "source_report": str(frozen_report_path),
        "workspace": str(workspace),
        "workspace_file_count": len(inventory),
        "frozen_report_untouched": True,
        "regime_definitions": {
            STRICT: (
                "Frozen one-strike rule: any presented, gate-eligible unresolved "
                "citation gates the full trajectory."
            ),
            CONSERVATIVE: (
                "Gate fully specified nonexistent paths and concrete unresolved "
                "wikilinks; retain malformed, abbreviated, annotated, and template locators."
            ),
            CLEAR: (
                "Gate only fully specified nonexistent provenance paths that cannot "
                "be reconciled to a frozen source."
            ),
        },
        "invariants": {
            "frozen_strict_gated_trajectories": len(frozen_gated),
            "audit_strict_gated_trajectories": len(derived_gated),
            "strict_gate_stems_match_frozen_report": derived_gated == frozen_gated,
            "missing_from_audit": sorted(frozen_gated - derived_gated),
            "extra_in_audit": sorted(derived_gated - frozen_gated),
        },
        "summary": {
            "unresolved_tokens": len(items),
            "trajectories_with_unresolved_tokens": len({str(i["stem"]) for i in items}),
            "category_counts": dict(sorted(category_counts.items())),
            "arm_category_counts": {
                arm: dict(sorted(counts.items()))
                for arm, counts in sorted(arm_category_counts.items())
            },
        },
        "items": items,
        "sensitivity": _sensitivity(frozen_report.get("rows") or [], items),
    }


def _fmt(value: Any) -> str:
    return "—" if value is None else f"{float(value):.3f}"


def render_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Agentic pilot provenance audit",
        "",
        "This is a non-destructive sensitivity analysis. The frozen trajectories, "
        "judgments, and `report.json` were not modified.",
        "",
        "## Integrity",
        "",
    ]
    inv = audit["invariants"]
    lines.extend([
        f"- Unresolved tokens: **{audit['summary']['unresolved_tokens']}**",
        (
            "- Trajectories with unresolved tokens: "
            f"**{audit['summary']['trajectories_with_unresolved_tokens']}**"
        ),
        (
            "- Strict gated trajectories reproduced: "
            f"**{inv['audit_strict_gated_trajectories']}** "
            f"(matches frozen report: **{inv['strict_gate_stems_match_frozen_report']}**)"
        ),
        "",
        "## Classification",
        "",
        "| category | unresolved tokens |",
        "|---|---:|",
    ])
    for category, count in audit["summary"]["category_counts"].items():
        lines.append(f"| `{category}` | {count} |")

    lines.extend([
        "",
        "## Primary-score sensitivity",
        "",
        "| arm | strict n/mean | conservative n/mean | clear-fabrication n/mean |",
        "|---|---:|---:|---:|",
    ])
    sensitivities = audit["sensitivity"]
    arms = sorted(sensitivities[STRICT]["per_arm"])
    for arm in arms:
        cells = []
        for regime in REGIMES:
            row = sensitivities[regime]["per_arm"][arm]
            cells.append(f"{row['n_included']}/{row['n_total']} · {_fmt(row['primary_mean'])}")
        lines.append(f"| `{arm}` | {' | '.join(cells)} |")

    lines.extend(["", "## CE QUERY unresolved tokens", ""])
    ce_items = [item for item in audit["items"] if item.get("arm") == "ce_query"]
    if not ce_items:
        lines.append("None.")
    else:
        lines.extend([
            "| trajectory | turn | category | raw token | clear fabrication? |",
            "|---|---|---|---|---:|",
        ])
        for item in ce_items:
            raw = str(item["raw"]).replace("|", "\\|").replace("\n", " ")
            lines.append(
                f"| `{item['stem']}` | {item['turn']} | `{item['category']}` "
                f"| `{raw}` | {'yes' if item['gates'][CLEAR] else 'no'} |"
            )

    for regime in REGIMES:
        lines.extend(["", f"## Paired comparisons: `{regime}`", ""])
        tests = sensitivities[regime]["paired_bootstrap_primary"]
        if not tests:
            lines.append("No comparison had at least three shared scenarios.")
            continue
        for name, result in sorted(tests.items()):
            lines.append(
                f"- **{name}**: Δ={result['mean_diff']:+.3f}, "
                f"CI95=[{result['ci95'][0]:+.3f}, {result['ci95'][1]:+.3f}], "
                f"P(Δ>0)={result['frac_boot_gt_zero']:.2f}, "
                f"n={result['n_scenarios']} scenarios."
            )

    lines.extend([
        "",
        "## Interpretation boundary",
        "",
        "The conservative and clear-fabrication views are retrospective sensitivity "
        "analyses, not replacements for the frozen preregistered result. They separate "
        "citation-syntax conformance from stronger claims of invented provenance.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-dir", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output-json", type=Path)
    parser.add_argument("--output-md", type=Path)
    args = parser.parse_args(argv)

    results_dir = args.results_dir.expanduser().resolve()
    workspace = args.workspace.expanduser().resolve()
    output_json = args.output_json or (results_dir / "provenance-audit.json")
    output_md = args.output_md or (results_dir / "provenance-audit.md")

    audit = build_audit(results_dir, workspace)
    output_json.write_text(json.dumps(audit, indent=2), encoding="utf-8")
    output_md.write_text(render_markdown(audit), encoding="utf-8")
    print(json.dumps({
        "output_json": str(output_json),
        "output_md": str(output_md),
        "unresolved_tokens": audit["summary"]["unresolved_tokens"],
        "strict_gate_match": audit["invariants"]["strict_gate_stems_match_frozen_report"],
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
