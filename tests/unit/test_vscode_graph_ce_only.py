"""The VS Code graph view mounts Curiosity Engine's viewer; the old
in-repo fork of CE's wiki-view is gone and nothing builds against it."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"
EXT = ROOT / "extensions" / "switchbay-vs"


def _sources() -> list[Path]:
    files: list[Path] = []
    for base, pats in (
        (FRONTEND / "src", ("*.ts", "*.tsx", "*.css", "*.html", "*.js")),
        (FRONTEND, ("*.html", "vite*.config.ts", "package.json")),
        (EXT / "src", ("*.ts",)),
        (EXT, ("package.json", ".vscodeignore")),
    ):
        for pat in pats:
            glob = base.rglob(pat) if base.name in {"src"} else base.glob(pat)
            files.extend(p for p in glob if "node_modules" not in p.parts)
    files.append(ROOT / "Makefile")
    return files


def test_fork_is_deleted():
    assert not (FRONTEND / "src" / "widgets" / "graph").exists()


def test_nothing_references_the_fork():
    offenders = [
        str(p.relative_to(ROOT))
        for p in _sources()
        if "widgets/graph" in p.read_text(errors="replace")
    ]
    assert offenders == []


def test_webview_entry_mounts_ce_viewer():
    src = (FRONTEND / "src" / "webview-graph.ts").read_text()
    assert "ceEmbedShell.html?raw" in src
    assert "loadCeModules" in src
    assert "CEEmbed" in src
    assert "installFetchBridge" in src


def test_extension_serves_ce_bundle_and_handles_missing_ce():
    src = (EXT / "src" / "webviews.ts").read_text()
    assert "ceViewerAvailable(" in src
    assert "Graph needs Curiosity Engine" in src
    assert "localResourceRoots: [mediaRoot, bundle]" in src
    assert "default-src 'none'" in src
    assert "answerCeApi(" in src
