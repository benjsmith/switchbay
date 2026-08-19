"""Slash-command tool palettes + budget clip."""

from __future__ import annotations

from pathlib import Path

from switchbay import command_palettes, tools  # noqa: F401 — populate registry
from switchbay.agents import rail_default


def _rung(ram: float = 17.2, hint: str = "Qwen3-4B-4bit"):
    return rail_default.resolve_local_rung(ram, model_hint=hint)


def test_deck_palette_is_just_deck_tools():
    rung = _rung()
    got = command_palettes.resolve(None, "create-deck", rung=rung)
    assert got is not None
    assert got.name == "deck"
    assert got.source == "shipped"
    names = set(got.tools)
    assert "author_slide" in names
    assert "make_slides_from_doc" in names
    assert "search_wiki" in names
    assert "ce_run" not in names
    assert "ce_sweep" not in names
    assert "create_report" not in names
    # Default RAM desk still bans decks; the command desk opts them in.
    chat = set(rung.chat_tools)
    assert "author_slide" not in chat


def test_curate_follows_rung_unless_overridden(tmp_path: Path):
    r16 = _rung(17.2, "Qwen3-4B-4bit")
    r48 = _rung(48, "Qwen3.8-27B")
    c16 = command_palettes.resolve(tmp_path, "curate", rung=r16)
    c48 = command_palettes.resolve(tmp_path, "curator", rung=r48)
    assert c16 is not None and c16.kind == "curate"
    assert c16.tools == r16.curate_tools
    assert "ce_ingest" not in c16.tools
    assert c48 is not None
    assert "ce_ingest" in c48.tools
    command_palettes.set_override(tmp_path, "curate", ["ce_epoch_summary", "search_wiki"])
    over = command_palettes.resolve(tmp_path, "curate", rung=r48)
    assert over is not None
    assert over.source == "override"
    assert list(over.tools) == ["ce_epoch_summary", "search_wiki"]


def test_ingest_is_not_the_curate_desk():
    rung = _rung()
    got = command_palettes.resolve(None, "drain", rung=rung)
    assert got is not None
    assert got.name == "ingest"
    assert "ce_ingest" in got.tools
    assert "ce_sweep" not in got.tools
    assert "author_slide" not in got.tools


def test_user_command_infers_tools(tmp_path: Path):
    rung = _rung()
    body = "Turn $ARGUMENTS into slides. Call author_slide on each heading."
    got = command_palettes.resolve(
        tmp_path, "weekly-update", rung=rung, template=body,
    )
    assert got is not None
    assert got.source == "inferred"
    assert "author_slide" in got.tools
    hinted = command_palettes.resolve(
        tmp_path, "make-me-a-deck", rung=rung,
        template="Please make a slide deck from the charter.",
    )
    assert hinted is not None
    assert "make_slides_from_doc" in hinted.tools


def test_unknown_command_without_tools_is_none():
    rung = _rung()
    assert command_palettes.resolve(None, "view", rung=rung) is None
    assert command_palettes.resolve(
        None, "mystery", rung=rung, template="Say hello.",
    ) is None


def test_report_drops_create_report_on_small_rung():
    r16 = _rung()
    r48 = _rung(48, "Qwen3.8-27B")
    small = command_palettes.resolve(None, "report", rung=r16)
    large = command_palettes.resolve(None, "report", rung=r48)
    assert small is not None
    assert "create_report" not in small.tools
    assert large is not None
    assert "create_report" in large.tools


def test_override_can_keep_strong_tool_on_small_rung(tmp_path: Path):
    rung = _rung()
    command_palettes.set_override(
        tmp_path, "report", ["search_wiki", "create_report"],
    )
    got = command_palettes.resolve(tmp_path, "report", rung=rung)
    assert got is not None
    assert "create_report" in got.tools


def test_deck_fits_ram16_budget():
    rung = _rung()
    got = command_palettes.resolve(None, "deck", rung=rung)
    assert got is not None
    system, specs, _m, stats = rail_default.assemble_local_prompt(
        palette="cmd:deck",
        only_tools=got.tools,
        rung=rung,
        messages=[{"role": "user", "content": "make slides from wiki/index.md"}],
    )
    assert {t["name"] for t in specs} >= {"author_slide", "make_slides_from_doc"}
    assert stats["total"] <= rung.prompt_budget
    assert "author_slide" in {t["name"] for t in specs}


def test_clip_drops_trailing_tools():
    rung = _rung()
    names = (
        "search_wiki",
        "read_wiki_page",
        "list_wiki_pages",
        "author_slide",
        "make_slides_from_doc",
        "make_slides_from_docs",
        "compose_analysis",
        "sketch_context",
        "sketch_show",
    )
    _sys, specs, _m, stats = rail_default.assemble_local_prompt(
        only_tools=names, rung=rung, budget=500,
        messages=[{"role": "user", "content": "hi"}],
    )
    assert stats["clipped_tools"]
    assert 1 <= len(specs) < len(names)
    assert specs[0]["name"] == "search_wiki"


def test_describe_all_includes_shipped_and_user_cmd(tmp_path: Path):
    rung = _rung()
    cmd_dir = tmp_path / ".workbench" / "commands"
    cmd_dir.mkdir(parents=True)
    (cmd_dir / "weekly.md").write_text(
        "Fill slides with author_slide.\n", encoding="utf-8",
    )
    payload = command_palettes.describe_all(tmp_path, rung)
    names = {c["name"] for c in payload["commands"]}
    assert "deck" in names
    assert "curate" in names
    assert "weekly" in names
    deck = next(c for c in payload["commands"] if c["name"] == "deck")
    assert "author_slide" in deck["tools"]
    assert payload["rung"]["id"] == "ram16"
    assert any(t["name"] == "author_slide" for t in payload["catalog"])


def test_set_and_clear_override(tmp_path: Path):
    saved = command_palettes.set_override(
        tmp_path, "deck", ["author_slide", "no-such-tool"],
    )
    assert saved == ["author_slide"]
    assert command_palettes.clear_override(tmp_path, "create-deck") is True
    assert command_palettes.clear_override(tmp_path, "deck") is False


def test_empty_override_resets(tmp_path: Path):
    command_palettes.set_override(tmp_path, "deck", ["author_slide"])
    assert command_palettes.set_override(tmp_path, "deck", []) == []
    got = command_palettes.resolve(tmp_path, "deck", rung=_rung())
    assert got is not None
    assert got.source == "shipped"
    assert "make_slides_from_doc" in got.tools
