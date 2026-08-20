"""Local-model tool palettes + prompt token budget (P1)."""

from __future__ import annotations

from switchbay import ce_tools, daemon, localllm
from switchbay.agents import rail_default


def _names(ram: float, hint: str = "", palette: str = "curate") -> set[str]:
    return {
        t["name"]
        for t in rail_default.tools_for_provider(
            local=True, palette=palette, ram_gb=ram, model_hint=hint,
        )
    }


def test_curate_palette_is_a_small_subset():
    full = rail_default.tools_for_provider(local=False)
    curate = rail_default.tools_for_provider(local=True, palette="curate")
    chat = rail_default.tools_for_provider(local=True, palette="chat")
    full_names = {t["name"] for t in full}
    curate_names = {t["name"] for t in curate}
    chat_names = {t["name"] for t in chat}
    assert "ce_epoch_summary" in curate_names
    assert "propose_wiki_page" in curate_names
    assert "search_wiki" in curate_names
    # Heavy / slop-prone tools stay off the default 16 GB / 4B palette.
    for banned in (
        "ce_sweep", "ce_run", "ce_ingest", "ce_graph_rebuild",
        "ce_planner", "create_report", "ask_thread",
        "make_slides_from_doc", "table_run_sql",
    ):
        assert banned not in curate_names
        assert banned not in chat_names
    assert curate_names < full_names
    assert len(curate) <= 12
    assert len(chat) <= 12


def test_ram_rungs_expand_and_never_include_ui_toolbox():
    n16 = _names(17.2, "Qwen3-4B-4bit")
    n32 = _names(32, "Qwen3.8-27B")
    n48 = _names(48, "Qwen3.8-27B")
    n64 = _names(64, "Qwen3.8-27B")
    n96 = _names(96, "Qwen3.8-27B")
    n128 = _names(128, "Qwen3-70B")
    assert n16 < n32 < n48 < n64 < n96 < n128
    assert "ce_sweep" not in n16
    assert "ce_sweep" in n32 and "ce_planner" in n32
    assert "ce_ingest" in n48 and "ce_graph_retrieve" in n48
    assert "ce_score_diff" in n64
    assert "ce_run" in n96
    assert "propose_split" in n128
    for names in (n16, n32, n48, n64, n96, n128):
        assert "create_report" not in names
        assert "ask_thread" not in names
        assert "table_run_sql" not in names
        assert "make_slides_from_doc" not in names


def test_small_model_on_big_mac_stays_worker():
    rung = rail_default.resolve_local_rung(128, model_hint="mlx-community/Qwen3-4B-4bit")
    assert rung.id == "ram16"
    assert rung.force_scaffold is True
    assert rung.prompt_budget == 2800
    assert rung.recommended_ctx == 8192
    assert "ce_sweep" not in _names(128, "Qwen3-4B-4bit")
    chat = _names(128, "Qwen3-4B-4bit", palette="chat")
    assert "search_wiki" in chat
    assert "wiki_neighbors" not in chat
    assert "recall_rail" not in chat


def test_27b_on_48gb_is_27b_class():
    rung = rail_default.resolve_local_rung(48, model_hint="Qwen3.8-27B")
    assert rung.id == "ram48"
    assert rung.force_scaffold is False
    assert rung.recommended_ctx == 65536
    assert rail_default.parse_param_b("Qwen3.8-27B") == 27.0


def test_27b_on_32gb_clips_to_32():
    assert rail_default.resolve_local_rung(32, model_hint="Qwen3.8-27B").id == "ram32"


def test_unknown_model_follows_ram():
    assert rail_default.resolve_local_rung(64, model_hint="custom-local").id == "ram64"


def test_27b_caps_at_96_even_on_128gb():
    assert rail_default.resolve_local_rung(128, model_hint="Qwen3.8-27B").id == "ram96"
    assert _names(128, "Qwen3.8-27B") == _names(96, "Qwen3.8-27B")


def test_48gb_curate_prompt_allows_pages():
    rung = rail_default.resolve_local_rung(48, model_hint="Qwen3.8-27B")
    extra = daemon._ce_action_prompt("curate", "", local=True, local_rung=rung) or ""
    assert "one target" in extra.lower() or "planner" in extra.lower()
    _sys, specs, _m, stats = rail_default.assemble_local_prompt(
        palette="curate", extra_system=extra, rung=rung,
        messages=[{"role": "user", "content": extra}],
    )
    assert stats["total"] <= rung.prompt_budget
    assert stats["rung"] == "ram48"
    assert {t["name"] for t in specs} >= {"ce_sweep", "ce_planner", "ce_ingest"}


def test_mechanical_hygiene_records_each_verb(monkeypatch):
    seen: list[str] = []

    def fake_sweep(_ws, payload):
        seen.append(str(payload.get("verb")))
        return {"stdout": f"{payload.get('verb')} ok"}

    monkeypatch.setattr(ce_tools, "_ce_sweep", fake_sweep)
    out = ce_tools.mechanical_hygiene("/tmp")
    assert seen == list(ce_tools.MECHANICAL_SWEEP_VERBS)
    assert out["ok"]
    assert "scan" in rail_default.format_sweep_prelude(out)


def test_local_curate_prompt_fits_budget():
    extra = daemon._ce_action_prompt("curate", "", local=True) or ""
    extra += "\n" + daemon._curator_profile_system("Treat X as an entity. " * 80)
    system, specs, _msgs, stats = rail_default.assemble_local_prompt(
        palette="curate",
        extra_system=extra,
        harness=localllm.DEFAULT_HARNESS,
        messages=[{"role": "user", "content": extra}],
    )
    assert stats["total"] <= rail_default.LOCAL_PROMPT_TOKEN_BUDGET
    assert stats["n_tools"] == len(specs)
    assert "ce_sweep" not in system
    assert "scaffold" in extra.lower() or "scaffold" in system.lower()
    # Old full-list dump was ~15k tokens of tools alone.
    full = rail_default.tools_for_provider(local=False)
    full_tools = rail_default.estimate_tokens(
        __import__("json").dumps(full),
    )
    assert stats["tools"] < full_tools
    assert stats["tools"] < 2500


def test_assemble_trims_old_messages():
    blob = "x" * 8000
    messages = (
        [{"role": "user", "content": blob}]
        + [{"role": "assistant", "content": blob}] * 6
        + [{"role": "user", "content": "last"}]
    )
    _sys, _tools, kept, stats = rail_default.assemble_local_prompt(
        palette="chat", messages=messages, budget=2000,
    )
    assert stats["total"] <= 2000
    assert stats["trimmed"] >= 1
    assert kept[-1]["content"] == "last"


def test_clip_messages_keeps_tool_result_shape():
    """A 4B + search_wiki used to stringify/overflow into a 15k prefill.

    Clipping must leave a `tool_result` block so the OpenAI-compat
    converter still emits a `tool` role, not a junk user string.
    """
    rung = rail_default.resolve_local_rung(16, model_hint="Qwen3-4B-4bit")
    specs = rail_default.tools_for_provider(
        local=True, palette="chat", rung=rung,
    )
    system = rail_default.LOCAL_SYSTEM_PROMPT
    hit = "Active learning. " + ("claim " * 400)
    messages = [
        {"role": "user", "content": "what do we know about active learning?"},
        {"role": "assistant", "content": [{
            "type": "tool_use", "id": "call_1", "name": "search_wiki",
            "input": {"query": "active learning"},
        }]},
        {"role": "user", "content": [{
            "type": "tool_result", "tool_use_id": "call_1",
            "content": __import__("json").dumps({
                "ok": True,
                "hits": [{"page": "active-learning", "snippet": hit}] * 12,
            }),
        }]},
    ]
    kept = rail_default.clip_messages_to_budget(
        system, specs, messages, rung.prompt_budget,
    )
    stats = rail_default.prompt_token_breakdown(system, specs, kept)
    assert stats["total"] <= rung.prompt_budget
    assert kept[0]["content"] == "what do we know about active learning?"
    last = kept[-1]["content"]
    assert isinstance(last, list)
    assert last[0]["type"] == "tool_result"
    assert last[0]["tool_use_id"] == "call_1"
    assert "clipped for local context" in str(last[0]["content"]) or len(
        str(last[0]["content"]),
    ) < 20_000


def test_local_propose_blurb_is_scaffold():
    specs = rail_default.tools_for_provider(local=True, palette="curate")
    prop = next(t for t in specs if t["name"] == "propose_wiki_page")
    assert "scaffold" in prop["description"].lower()
    assert "scaffold" in (prop.get("input_schema") or {}).get("properties", {})


def test_local_ce_prompt_is_worker_not_sweep():
    p = daemon._ce_action_prompt("curate", "", local=True) or ""
    assert "ce_sweep" not in p
    assert "scaffold" in p.lower()
    assert "never deletes" in p.lower()
    strong = daemon._ce_action_prompt("curate", "", local=False) or ""
    assert "ce_sweep" in strong
