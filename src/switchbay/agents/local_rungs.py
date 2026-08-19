"""RAM-scaled local-model tool palettes.

Every local model still gets a palette (never the full rail). Machine
RAM picks the widest desk that fits; the loaded model's size caps it
so a 4B on a 128 GB Mac stays a worker.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

_STRONG_ONLY_TOOLS = {"create_report"}
_LOCAL_NEVER_TOOLS = _STRONG_ONLY_TOOLS | {
    "create_report",
    "make_slides_from_doc",
    "make_slides_from_docs",
    "compose_analysis",
    "author_slide",
    "save_plot",
    "sheet_context",
    "sheet_select",
    "sheet_set_formula",
    "sheet_set_values",
    "table_context",
    "table_run_sql",
    "plot_context",
    "plot_update",
    "plot_show",
    "sketch_context",
    "sketch_show",
    "list_threads",
    "ask_thread",
    "list_duckdb_starters",
    "add_duckdb_starters",
    "replace_duckdb_starters",
}

LOCAL_CHAT_TOOLS: tuple[str, ...] = (
    "search_wiki",
    "read_wiki_page",
    "list_wiki_pages",
    "wiki_neighbors",
    "recall_rail",
    "list_skills",
    "load_skill",
    "propose_wiki_page",
    "propose_page_edit",
)
LOCAL_CURATE_TOOLS: tuple[str, ...] = (
    "ce_epoch_summary",
    "search_wiki",
    "list_wiki_pages",
    "read_wiki_page",
    "wiki_neighbors",
    "propose_wiki_page",
    "propose_page_edit",
    "list_skills",
    "load_skill",
)

_ADD_32 = (
    "ce_sweep", "ce_lint", "ce_planner", "ce_graph_rebuild",
    "wiki_path", "wiki_shared_sources",
)
_ADD_48 = (
    "ce_graph_retrieve", "ce_vault_search", "ce_graph_neighbors",
    "ce_graph_path", "ce_scan", "ce_query", "ce_ingest",
    "ce_bridge_candidates", "wiki_related_by_sources",
)
_ADD_64 = (
    "ce_vault_index", "ce_score_diff", "ce_scrub_check", "ce_naming",
    "ce_tables", "ce_figures", "propose_charter_edit",
    "ce_shared_sources",
)
_ADD_96 = (
    "ce_run", "read_workspace_plan", "update_work_plan",
    "append_workspace_log",
)
_ADD_128 = (
    "register_rule", "list_rules", "delete_rule", "propose_split",
)

_PARAM_B_RE = re.compile(r"(?<![0-9])(\d+(?:\.\d+)?)[bB](?![a-zA-Z0-9])")


def _uniq(*parts: tuple[str, ...]) -> tuple[str, ...]:
    seen: list[str] = []
    for part in parts:
        for n in part:
            if n not in seen and n not in _LOCAL_NEVER_TOOLS:
                seen.append(n)
    return tuple(seen)


@dataclass(frozen=True)
class LocalRung:
    """Compiled local-model desk: tools, budget, write policy."""

    id: str
    min_ram_gb: float
    label: str
    prompt_budget: int
    extra_system_chars: int
    force_scaffold: bool
    recommended_ctx: int
    chat_tools: tuple[str, ...]
    curate_tools: tuple[str, ...]
    blurb: str

    def to_public(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "min_ram_gb": self.min_ram_gb,
            "label": self.label,
            "prompt_budget": self.prompt_budget,
            "force_scaffold": self.force_scaffold,
            "recommended_ctx": self.recommended_ctx,
            "n_tools_chat": len(self.chat_tools),
            "n_tools_curate": len(self.curate_tools),
            "blurb": self.blurb,
        }


LOCAL_RUNGS: tuple[LocalRung, ...] = (
    LocalRung(
        id="ram16", min_ram_gb=16, label="16 GB worker",
        prompt_budget=3500, extra_system_chars=1600,
        force_scaffold=True, recommended_ctx=32768,
        chat_tools=LOCAL_CHAT_TOOLS, curate_tools=LOCAL_CURATE_TOOLS,
        blurb="Classify, search, light Reviews scaffolds. Host runs mechanical sweep.",
    ),
    LocalRung(
        id="ram32", min_ram_gb=32, label="32 GB local-large",
        prompt_budget=8000, extra_system_chars=2400,
        force_scaffold=True, recommended_ctx=32768,
        chat_tools=_uniq(LOCAL_CHAT_TOOLS, _ADD_32),
        curate_tools=_uniq(LOCAL_CURATE_TOOLS, _ADD_32),
        blurb="Worker writes + sweep/lint/planner to orient. Host already ran mechanical sweep.",
    ),
    LocalRung(
        id="ram48", min_ram_gb=48, label="48 GB 27B-class",
        prompt_budget=16000, extra_system_chars=4000,
        force_scaffold=False, recommended_ctx=65536,
        chat_tools=_uniq(LOCAL_CHAT_TOOLS, _ADD_32, _ADD_48),
        curate_tools=_uniq(LOCAL_CURATE_TOOLS, _ADD_32, _ADD_48),
        blurb="Sourced wiki pages, retrieve, ingest, planner pick-mode. One target per turn.",
    ),
    LocalRung(
        id="ram64", min_ram_gb=64, label="64 GB curator",
        prompt_budget=24000, extra_system_chars=6000,
        force_scaffold=False, recommended_ctx=65536,
        chat_tools=_uniq(LOCAL_CHAT_TOOLS, _ADD_32, _ADD_48, _ADD_64),
        curate_tools=_uniq(LOCAL_CURATE_TOOLS, _ADD_32, _ADD_48, _ADD_64),
        blurb="Full CE named tools (score_diff, tables, figures). Still no decks/sheets/A2A.",
    ),
    LocalRung(
        id="ram96", min_ram_gb=96, label="96 GB wide curator",
        prompt_budget=32000, extra_system_chars=8000,
        force_scaffold=False, recommended_ctx=131072,
        chat_tools=_uniq(LOCAL_CHAT_TOOLS, _ADD_32, _ADD_48, _ADD_64, _ADD_96),
        curate_tools=_uniq(LOCAL_CURATE_TOOLS, _ADD_32, _ADD_48, _ADD_64, _ADD_96),
        blurb="Adds ce_run for extra CE scripts. Palettes stay — not the UI toolbox.",
    ),
    LocalRung(
        id="ram128", min_ram_gb=128, label="128 GB max local",
        prompt_budget=48000, extra_system_chars=12000,
        force_scaffold=False, recommended_ctx=131072,
        chat_tools=_uniq(LOCAL_CHAT_TOOLS, _ADD_32, _ADD_48, _ADD_64, _ADD_96, _ADD_128),
        curate_tools=_uniq(LOCAL_CURATE_TOOLS, _ADD_32, _ADD_48, _ADD_64, _ADD_96, _ADD_128),
        blurb="Widest local curate palette. Decks, sheets, and A2A stay off.",
    ),
)


def parse_param_b(hint: str) -> float | None:
    """Best-effort parameter count from a model id/label/repo."""
    found: list[float] = []
    for m in _PARAM_B_RE.finditer(hint or ""):
        v = float(m.group(1))
        if 0.4 <= v <= 400:
            found.append(v)
    return max(found) if found else None


def model_hint_from_cfg(cfg: dict[str, Any] | None) -> str:
    if not cfg:
        return ""
    return " ".join(
        str(cfg.get(k) or "")
        for k in ("model_label", "candidate_id", "repo", "model", "alias", "file")
    )


def model_max_ram_floor(params_b: float | None) -> float:
    """Highest RAM palette this model can use. RAM then clips down."""
    if params_b is None:
        return 999.0
    if params_b < 10:
        return 16.0
    if params_b < 20:
        return 32.0
    if params_b < 40:
        return 96.0
    return 128.0


def resolve_local_rung(
    ram_gb: float | None = None,
    *,
    model_hint: str = "",
) -> LocalRung:
    """Pick the local desk from machine RAM, capped by loaded model size."""
    ram = 16.0 if ram_gb is None else float(ram_gb)
    params = parse_param_b(model_hint)
    cap = model_max_ram_floor(params)
    effective = min(ram, cap)
    chosen = LOCAL_RUNGS[0]
    for rung in LOCAL_RUNGS:
        if effective + 1.5 >= rung.min_ram_gb:
            chosen = rung
    return chosen


def format_sweep_prelude(report: dict[str, Any]) -> str:
    lines = [
        "Mechanical sweep (host, already ran — do not repeat "
        "scan / fix-index / fix-source-stubs / sync-notes / sync-todos):",
    ]
    for step in report.get("steps") or []:
        verb = step.get("verb") or "?"
        if step.get("ok"):
            status = "ok"
        else:
            status = f"err {step.get('error') or 'failed'}"
        prev = str(step.get("preview") or "").replace("\n", " ").strip()
        if prev:
            lines.append(f"- {verb}: {status} · {prev[:160]}")
        else:
            lines.append(f"- {verb}: {status}")
    return "\n".join(lines)
