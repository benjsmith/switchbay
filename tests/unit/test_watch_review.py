"""Independent release probes: preserve data, approvals and concurrent receipts."""
import hashlib
import os
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from switchbay import ce_tools, watchfolders, workspaces


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setenv('SWITCHBAY_STATE_DIR', str(tmp_path/'state'))
    monkeypatch.setattr(workspaces, 'is_within_home', lambda p: True)
    ws=tmp_path/'ws'; ws.mkdir()
    folder=tmp_path/'watched'; folder.mkdir()
    watchfolders.add_folder(ws,str(folder))
    src=folder/'fixture.txt'; src.write_text('Synthetic source text. '*30)
    cand=watchfolders.Candidate(path=str(src),logical=str(src),folder=str(folder),size=src.stat().st_size,mtime=time.time()-60,ext='.txt')
    return ws,folder,src,cand

def test_failed_retry_never_deletes_preexisting_vault_copy(setup):
    ws,folder,src,cand=setup
    rel,_=watchfolders.stage_file(ws,src)
    existing=ws/rel; data=existing.read_bytes()
    watchfolders.handoff(ws,cand,ingest=lambda *a:{'ok':False,'error':'fixture extraction failed'})
    assert existing.exists(), 'Failed retry deleted a pre-existing vault source'
    assert existing.read_bytes()==data

def test_symlink_swap_after_scan_cannot_escape_authorized_folder(setup):
    ws,folder,src,cand=setup
    outside=folder.parent/'outside.txt'; outside.write_text('OUTSIDE-SECRET-MARKER '*20)
    src.unlink(); src.symlink_to(outside)
    calls=[]
    result=watchfolders.handoff(ws,cand,ingest=lambda *a:calls.append(a) or {'ok':True})
    assert not calls, 'File replaced with escaping symlink was handed to extractor'
    assert result.status!='success'
    assert not any('OUTSIDE-SECRET-MARKER' in p.read_text(errors='ignore') for p in (ws/'vault').rglob('*') if p.is_file())

def test_concurrent_seen_receipts_are_not_lost(setup,monkeypatch):
    ws,*_=setup
    original=watchfolders._load_seen
    def slow_load(w):
        value=original(w); time.sleep(.003); return value
    monkeypatch.setattr(watchfolders,'_load_seen',slow_load)
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda n:watchfolders.mark_seen(ws,f'file-{n}',mtime=1,size=10),range(40)))
    seen=original(ws)
    assert len(seen)==40, f'Lost concurrent seen receipts: kept {len(seen)}/40'

def test_concurrent_pending_retries_are_not_lost(setup,monkeypatch):
    ws,*_=setup
    original=watchfolders._load_pending
    def slow_load(w):
        value=original(w); time.sleep(.003); return value
    monkeypatch.setattr(watchfolders,'_load_pending',slow_load)
    with ThreadPoolExecutor(max_workers=10) as pool:
        list(pool.map(lambda n:watchfolders.record_pending(ws,f'file-{n}',state='hydrating',error='waiting'),range(40)))
    pending=original(ws)
    assert len(pending)==40, f'Lost concurrent pending receipts: kept {len(pending)}/40'

def test_valid_document_can_quote_extractor_error_messages(setup):
    ws,*_=setup
    page=ws/'vault'/'valid.pptx.extracted.md'
    page.parent.mkdir(parents=True,exist_ok=True)
    page.write_text('---\nextraction_method: python-pptx\nextraction_quality: good\n---\n\n# Troubleshooting documentation\n\nThis legitimate slide quotes the message "PPTX extraction unavailable" and explains how to fix it.\n')
    out={'ok':1,'considered':1,'failed':0,'results':[{'ok':True,'extracted':str(page),'extraction_method':'python-pptx','extraction_quality':'good'}]}
    result=ce_tools._reject_failed_structured_extracts(ws,out)
    assert result.get('ok'), 'Valid research text was misclassified as an extraction error'
    assert page.exists(), 'Valid extracted content was discarded'

def test_permanent_offline_backoff_does_not_overflow():
    delay=watchfolders._backoff(10000)
    assert 0 < delay <= watchfolders.MAX_BACKOFF


def test_watcher_provenance_is_preserved_in_vault_index(setup):
    from switchbay import cebridge
    ws, *_rest, cand = setup
    if not (cebridge.ce_root() / 'scripts/local_ingest.py').is_file():
        pytest.skip('optional curiosity-engine installation absent')
    result = watchfolders.handoff(ws, cand)
    assert result.status == 'success', result
    assert result.vault_rel and (ws / result.vault_rel).is_file(), 'Watcher returned a deleted staging path'
    db = ws / 'vault' / 'vault.db'
    assert db.is_file()
    with sqlite3.connect(db) as conn:
        sources = [r[0] for r in conn.execute('SELECT source_path FROM sources')]
    assert cand.logical in sources, f'Index lost original watcher provenance: {sources}'

    extracted = ws / result.extracted
    rel = str(extracted.relative_to(ws / 'vault'))
    with sqlite3.connect(db) as conn:
        row = conn.execute('SELECT sha256 FROM source_meta WHERE path = ?', (rel,)).fetchone()
    assert row and row[0] == hashlib.sha256(extracted.read_bytes()).hexdigest(), 'Provenance rewrite left stale indexed hash'


def test_staging_rejects_same_size_source_changed_within_one_second(setup):
    ws, folder, src, cand = setup
    before = src.stat()
    original = src.read_bytes()
    src.write_bytes(b'Z' * len(original))
    os.utime(src, ns=(before.st_atime_ns, before.st_mtime_ns + 250_000_000))
    with pytest.raises(OSError, match='changed'):
        watchfolders._copy_bounded(src, ws / 'copied.txt', timeout=5, expected_size=before.st_size, expected_mtime=before.st_mtime)


_QUOTE = (
    'This legitimate slide quotes the message "PPTX extraction unavailable" '
    'and explains how to fix it.\n'
)


@pytest.mark.parametrize("quality,method", [
    ("good", "python-pptx"),
    ("partial", "python-pptx"),
    ("thin", "utf8"),
    ("unknown", "utf8"),
    ("", "utf8"),
])
def test_valid_nonfailed_quality_can_quote_extractor_errors(setup, quality, method):
    ws, *_ = setup
    page = ws / "vault" / f"valid-{quality or 'none'}.pptx.extracted.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    fm = [f"extraction_method: {method}"]
    if quality:
        fm.append(f"extraction_quality: {quality}")
    page.write_text("---\n" + "\n".join(fm) + "\n---\n\n# Notes\n\n" + _QUOTE)
    row = {"ok": True, "extracted": str(page), "extraction_method": method}
    if quality:
        row["extraction_quality"] = quality
    out = {"ok": 1, "considered": 1, "failed": 0, "results": [row]}
    result = ce_tools._reject_failed_structured_extracts(ws, out)
    assert result.get("ok"), result
    assert page.exists(), "Valid extracted content was discarded"


def test_valid_document_without_metadata_can_quote_extractor_errors(setup):
    ws, *_ = setup
    page = ws / "vault" / "notes.extracted.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text("# Research notes\n\n" + _QUOTE)
    out = {
        "ok": 1, "considered": 1, "failed": 0,
        "results": [{"ok": True, "extracted": str(page)}],
    }
    result = ce_tools._reject_failed_structured_extracts(ws, out)
    assert result.get("ok"), result
    assert page.exists()


def test_generated_failed_fallback_metadata_is_still_rejected(setup):
    ws, *_ = setup
    page = ws / "vault" / "missing.pptx.extracted.md"
    page.parent.mkdir(parents=True, exist_ok=True)
    page.write_text(
        "---\nextraction_method: pptx_failed\nextraction_quality: failed\n---\n\n"
        "(PPTX extraction unavailable — `python-pptx` not installed.)\n"
    )
    out = {
        "ok": 1, "considered": 1, "failed": 0,
        "results": [{
            "ok": True, "extracted": str(page),
            "extraction_method": "pptx_failed",
            "extraction_quality": "failed",
        }],
    }
    result = ce_tools._reject_failed_structured_extracts(ws, out)
    assert result.get("ok") is False
    assert result.get("retryable") is True
    assert not page.exists()


def test_rejected_extract_removed_from_index_similar_name_unchanged(setup):
    ws, *_ = setup
    vault = ws / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    good = vault / "good.txt.extracted.md"
    bad = vault / "corrupt.pptx.extracted.md"
    decoy = vault / "also_corrupt.pptx.extracted.md"
    good.write_text(
        "---\nextraction_method: utf8\nextraction_quality: good\n---\n\n"
        "GOOD-KEEP-MARKER\n"
    )
    bad.write_text(
        "---\nextraction_method: pptx_failed\nextraction_quality: failed\n---\n\n"
        "(PPTX extraction unavailable)\n"
    )
    decoy.write_text("UNRELATED-DECOY-BODY\n")
    db = vault / "vault.db"
    decoy_hash = hashlib.sha256(decoy.read_bytes()).hexdigest()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE VIRTUAL TABLE sources USING fts5("
            "path, title, body, date, source_path)"
        )
        conn.execute(
            "CREATE TABLE source_meta ("
            "path TEXT PRIMARY KEY, sha256 TEXT, indexed_at TEXT)"
        )
        for p, src in (
            (good, str(good)),
            (bad, str(bad)),
            (decoy, "/unrelated/also_corrupt.pptx"),
        ):
            rel = p.name
            conn.execute(
                "INSERT INTO sources(path, title, body, date, source_path) "
                "VALUES(?,?,?,?,?)",
                (rel, rel, p.read_text(encoding="utf-8"), "", src),
            )
            conn.execute(
                "INSERT INTO source_meta(path, sha256, indexed_at) "
                "VALUES(?,?,?)",
                (rel, hashlib.sha256(p.read_bytes()).hexdigest(), "now"),
            )
        conn.commit()
    original_bin = vault / "corrupt.pptx"
    original_bin.write_bytes(b"PK\x03\x04 not a real deck")
    out = {
        "ok": 2, "considered": 2, "failed": 0,
        "results": [
            {
                "ok": True, "extracted": str(good),
                "extraction_method": "utf8", "extraction_quality": "good",
            },
            {
                "ok": True, "extracted": str(bad),
                "extraction_method": "pptx_failed",
                "extraction_quality": "failed",
                "indexed": {"path": bad.name},
            },
        ],
    }
    result = ce_tools._reject_failed_structured_extracts(ws, out)
    assert result.get("ok") == 1, result
    assert result.get("failed") == 1, result
    assert len(result.get("results") or []) == 1
    assert good.exists()
    assert not bad.exists()
    assert original_bin.exists()
    with sqlite3.connect(db) as conn:
        paths = [r[0] for r in conn.execute("SELECT path FROM sources")]
        meta = {
            r[0]: r[1]
            for r in conn.execute("SELECT path, sha256 FROM source_meta")
        }
        bodies = {
            r[0]: r[1]
            for r in conn.execute("SELECT path, body FROM sources")
        }
        decoy_src = conn.execute(
            "SELECT source_path FROM sources WHERE path = ?", (decoy.name,),
        ).fetchone()
    assert bad.name not in paths
    assert bad.name not in meta
    assert good.name in paths
    assert "GOOD-KEEP-MARKER" in (bodies.get(good.name) or "")
    assert decoy.name in paths
    assert meta.get(decoy.name) == decoy_hash
    assert decoy_src and decoy_src[0] == "/unrelated/also_corrupt.pptx"


def test_provenance_update_does_not_touch_similar_index_names(setup):
    ws, *_ = setup
    vault = ws / "vault"
    vault.mkdir(parents=True, exist_ok=True)
    target = vault / "fixture.txt.extracted.md"
    decoy = vault / "also_fixture.txt.extracted.md"
    target.write_text("---\nsource_path: /watched/fixture.txt\n---\n\nbody\n")
    decoy.write_text("DECOY-BODY\n")
    db = vault / "vault.db"
    decoy_hash = hashlib.sha256(decoy.read_bytes()).hexdigest()
    with sqlite3.connect(db) as conn:
        conn.execute(
            "CREATE VIRTUAL TABLE sources USING fts5("
            "path, title, body, date, source_path)"
        )
        conn.execute(
            "CREATE TABLE source_meta ("
            "path TEXT PRIMARY KEY, sha256 TEXT, indexed_at TEXT)"
        )
        for p, src in ((target, "old"), (decoy, "/unrelated/also_fixture.txt")):
            conn.execute(
                "INSERT INTO sources(path, title, body, date, source_path) "
                "VALUES(?,?,?,?,?)",
                (p.name, p.name, p.read_text(encoding="utf-8"), "", src),
            )
            conn.execute(
                "INSERT INTO source_meta(path, sha256, indexed_at) "
                "VALUES(?,?,?)",
                (p.name, hashlib.sha256(p.read_bytes()).hexdigest(), "now"),
            )
        conn.commit()
    watchfolders._set_index_source_path_exact(
        ws, watchfolders.extract_index_paths(ws, target), "/watched/fixture.txt",
    )
    with sqlite3.connect(db) as conn:
        decoy_row = conn.execute(
            "SELECT source_path, body FROM sources WHERE path = ?",
            (decoy.name,),
        ).fetchone()
        decoy_meta = conn.execute(
            "SELECT sha256 FROM source_meta WHERE path = ?", (decoy.name,),
        ).fetchone()
        target_src = conn.execute(
            "SELECT source_path FROM sources WHERE path = ?", (target.name,),
        ).fetchone()
    assert decoy_row == ("/unrelated/also_fixture.txt", "DECOY-BODY\n")
    assert decoy_meta and decoy_meta[0] == decoy_hash
    assert target_src and target_src[0] == "/watched/fixture.txt"


def test_success_cleans_stage_only_when_ce_kept_separate_source(setup):
    ws, folder, src, cand = setup
    kept = ws / "vault" / "kept-original.txt"
    kept.parent.mkdir(parents=True, exist_ok=True)

    def ingest(workspace, rel, timeout):
        del timeout
        data = (workspace / rel).read_bytes()
        kept.write_bytes(data)
        extracted = ws / "vault" / "note.extracted.md"
        extracted.write_text("payload\n", encoding="utf-8")
        return {
            "ok": 1,
            "results": [{
                "ok": True, "extracted": str(extracted),
                "kept": str(kept),
                "extraction_method": "utf8", "extraction_quality": "good",
            }],
        }

    result = watchfolders.handoff(ws, cand, ingest=ingest)
    assert result.status == "success", result
    assert kept.is_file()
    assert src.is_file()
    assert result.vault_rel
    assert (ws / result.vault_rel).is_file()
    assert (ws / result.vault_rel).resolve() == kept.resolve()
    stage_root = ws / "vault" / ".watch-ingest"
    leftover = [p for p in stage_root.rglob("*") if p.is_file()] if stage_root.exists() else []
    assert leftover == []


def test_success_keeps_stage_when_source_is_in_place(setup):
    ws, folder, src, cand = setup

    def ingest(workspace, rel, timeout):
        del timeout
        extracted = ws / "vault" / "note.extracted.md"
        extracted.parent.mkdir(parents=True, exist_ok=True)
        extracted.write_text("payload\n", encoding="utf-8")
        return {
            "ok": 1,
            "results": [{
                "ok": True, "extracted": str(extracted),
                "source_in_place": True,
                "extraction_method": "utf8", "extraction_quality": "good",
            }],
        }

    result = watchfolders.handoff(ws, cand, ingest=ingest)
    assert result.status == "success", result
    assert src.is_file()
    assert result.vault_rel
    assert (ws / result.vault_rel).is_file()
