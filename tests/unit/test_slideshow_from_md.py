"""Markdown → HTML slideshow parser + offline build."""

from __future__ import annotations

from pathlib import Path

from switchbay import slideshow_from_md, slideshow_html


SAMPLE = """# Attention tour

A short visual tour.

## The big idea

- Sequence modeling without recurrence
- Self-attention as the core primitive

image: A clean diagram of multi-head attention on a dark background

### Voiceover

The transformer replaced recurrence with self-attention.

## Core pieces

- Encoder and decoder stacks
- Multi-head attention
- Positional encodings

[[media-test-transformers-architecture]]

## Closing

- Still the backbone of modern LLMs

### TTS

That simple recipe still powers large language models today.
"""


def test_parse_h1_h2_counts():
    deck = slideshow_from_md.parse_markdown(SAMPLE)
    assert deck.title == "Attention tour"
    # title + 3 H2s
    assert len(deck.slides) == 4
    assert deck.slides[0].is_title
    assert deck.slides[0].lede.startswith("A short visual")
    assert deck.slides[1].heading == "The big idea"
    assert len(deck.slides[1].bullets) == 2
    assert deck.slides[1].image_prompts
    assert "transformer replaced" in deck.slides[1].voiceover.lower()
    assert deck.slides[2].figures  # wikilink recorded (path may be unresolved)
    assert "simple recipe" in deck.slides[3].voiceover.lower()


def test_ten_h2s_ten_content_slides():
    lines = ["# Deck", ""]
    for i in range(10):
        lines += [f"## Slide {i + 1}", "", f"- point {i + 1}", ""]
    deck = slideshow_from_md.parse_markdown("\n".join(lines))
    content = [s for s in deck.slides if not s.is_title]
    assert len(content) == 10


def test_list_image_prompt():
    md = """# T

## S

- normal bullet
- image: generate a cat wearing sunglasses
- another bullet
"""
    deck = slideshow_from_md.parse_markdown(md)
    s = deck.slides[1]
    assert s.bullets == ["normal bullet", "another bullet"]
    assert s.image_prompts == ["generate a cat wearing sunglasses"]


def test_resolve_figure(tmp_path: Path):
    assets = tmp_path / "wiki" / "figures" / "_assets"
    assets.mkdir(parents=True)
    png = assets / "demo-fig.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    found = slideshow_from_md.resolve_figure(tmp_path, "demo-fig")
    assert found == png.resolve()
    found2 = slideshow_from_md.resolve_figure(
        tmp_path, "figures/_assets/demo-fig.png",
    )
    assert found2 == png.resolve()


def test_build_offline_no_gen(tmp_path: Path):
    assets = tmp_path / "wiki" / "figures" / "_assets"
    assets.mkdir(parents=True)
    png = assets / "arch.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n")
    notes = tmp_path / "notes"
    notes.mkdir()
    md = notes / "my-deck.md"
    md.write_text(
        "# My Deck\n\nLede here.\n\n"
        "## With figure\n\n- a\n- b\n\n[[arch]]\n\n"
        "### Voiceover\n\nHello world narration.\n\n"
        "## Bullets only\n\n- x\n- y\n",
        encoding="utf-8",
    )
    result = slideshow_from_md.build_from_markdown(
        tmp_path,
        "notes/my-deck.md",
        slug="my-deck",
        generate_media=False,
    )
    assert result["ok"]
    assert result["slug"] == "my-deck"
    assert result["n_slides"] == 3
    d = tmp_path / "slideshows" / "my-deck"
    html = (d / "index.html").read_text(encoding="utf-8")
    assert "My Deck" in html
    assert "With figure" in html
    assert "VOICE_DELAY_MS=3000" in html
    assert "scheduleVoice" in html
    # figure copied
    assert any(p.suffix == ".png" for p in d.iterdir() if p.is_file())
    # no audio when gen off (script present only as notes)
    assert result["audio_slides"] == []


def test_write_slideshow_voice_delay_in_html(tmp_path: Path):
    r = slideshow_html.write_slideshow(
        tmp_path,
        "delay-demo",
        title="Delay",
        slides=[
            {"layout": "title", "heading": "Hi", "audio": "v.mp3"},
        ],
        voice_delay_ms=3000,
    )
    html = (tmp_path / "slideshows" / "delay-demo" / "index.html").read_text(
        encoding="utf-8",
    )
    assert "VOICE_DELAY_MS=3000" in html
    assert r["voice_delay_ms"] == 3000


def test_deck_to_slide_dicts_layouts():
    deck = slideshow_from_md.parse_markdown(SAMPLE)
    slides = slideshow_from_md.deck_to_slide_dicts(
        deck,
        media_names={1: "s1.png", 2: "s2.png"},
        audio_names={1: "s1.mp3"},
    )
    assert slides[0]["layout"] == "title"
    assert slides[1]["layout"] == "split"  # media + bullets
    assert slides[1]["audio"] == "s1.mp3"
    assert slides[1]["media"] == "s1.png"
