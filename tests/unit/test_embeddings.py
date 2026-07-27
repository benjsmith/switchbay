"""Pluggable embedder: the model-switch rebuild (CI-safe, sqlite-vec
only) and, when fastembed is installed, the full embed→recall path."""

from __future__ import annotations

import pytest

from switchbay import conversations as c


def _mk_ws(tmp_path):
    (tmp_path / ".workbench" / "state").mkdir(parents=True, exist_ok=True)
    return tmp_path


def _sqlite_vec_available() -> bool:
    try:
        import sqlite_vec  # noqa: F401
        import sqlite3
        conn = sqlite3.connect(":memory:")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        return True
    except Exception:
        return False


def _fastembed_available() -> bool:
    try:
        import fastembed  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.mark.skipif(not _sqlite_vec_available(), reason="sqlite-vec extension unavailable")
def test_reconcile_rebuilds_on_model_switch(tmp_path):
    import sqlite_vec
    ws = _mk_ws(tmp_path)
    tid = c.new_thread(ws)
    for t in ("alpha note", "beta note", "gamma note"):
        c.append_event(ws, tid, "note", t, source="user", actor="user")
    with c._connect(ws) as conn:
        assert c._ensure_vec_schema(conn)
        # Seed 3 vectors tagged with an OLD model, mark events embedded.
        for ev in conn.execute("SELECT id FROM events").fetchall():
            blob = sqlite_vec.serialize_float32([0.0] * c.EMBED_DIM)
            cur = conn.execute("INSERT INTO event_embeddings(embedding) VALUES (?)", (blob,))
            conn.execute(
                "INSERT INTO event_embeddings_meta(vec_rowid, event_id, model, created_at) "
                "VALUES (?, ?, 'old/model', 0)", (cur.lastrowid, ev["id"]))
            conn.execute("UPDATE events SET needs_embedding = 0 WHERE id = ?", (ev["id"],))
        assert conn.execute("SELECT COUNT(*) n FROM event_embeddings_meta").fetchone()["n"] == 3

        # Same model → no-op.
        c._reconcile_embed_model(conn, "old/model")
        assert conn.execute("SELECT COUNT(*) n FROM event_embeddings_meta").fetchone()["n"] == 3
        assert conn.execute("SELECT COUNT(*) n FROM events WHERE needs_embedding=1").fetchone()["n"] == 0

        # Different model → wipe vectors + re-mark every event for re-embed.
        c._reconcile_embed_model(conn, "new/model")
        assert conn.execute("SELECT COUNT(*) n FROM event_embeddings_meta").fetchone()["n"] == 0
        assert conn.execute("SELECT COUNT(*) n FROM events WHERE needs_embedding=1").fetchone()["n"] == 3


def test_vendor_backend_selected_and_normalizes(tmp_path, monkeypatch):
    # Explicit vendor backend + a key present → vendor _Embedder, which
    # posts to the API (mocked) and L2-normalises the result to 384-dim.
    from switchbay import app_settings
    c.reset_embedder()
    monkeypatch.setattr(app_settings, "get_embedding_backend", lambda: "openai")
    monkeypatch.setattr(c, "_vendor_key", lambda provider: "sk-test")

    captured = {}

    def fake_embed(backend, texts):
        captured["backend"] = backend
        captured["n"] = len(texts)
        # pretend the API returned un-normalised 384-dim vectors
        return [c._l2norm([0.3] * c.EMBED_DIM) for _ in texts]

    monkeypatch.setattr(c, "_vendor_embed", fake_embed)
    e = c._load_embedder()
    assert e is not None and e.backend == "vendor"
    assert e.model_id.startswith("openai:")
    q = e.embed_query("hello")
    assert len(q) == c.EMBED_DIM
    import math
    assert abs(math.sqrt(sum(x * x for x in q)) - 1.0) < 1e-6  # unit length
    assert captured["backend"] == "openai"
    c.reset_embedder()


def test_vendor_backend_no_key_fails_soft(tmp_path, monkeypatch):
    from switchbay import app_settings
    c.reset_embedder()
    monkeypatch.setattr(app_settings, "get_embedding_backend", lambda: "gemini")
    monkeypatch.setattr(c, "_vendor_key", lambda provider: None)
    assert c._load_embedder() is None  # no key → FTS-only, not a local fallback
    c.reset_embedder()


def test_l2norm_unit_length():
    v = c._l2norm([3.0, 4.0])
    import math
    assert abs(math.sqrt(v[0] ** 2 + v[1] ** 2) - 1.0) < 1e-9
    assert c._l2norm([0.0, 0.0]) == [0.0, 0.0]  # zero vector safe


def test_embedder_absent_is_fail_soft(tmp_path, monkeypatch):
    # Local backend + neither ML lib installed → None (FTS-only).
    from switchbay import app_settings
    monkeypatch.setattr(app_settings, "get_embedding_backend", lambda: "auto")
    monkeypatch.setattr(c, "_embedder", None)
    import builtins
    real_import = builtins.__import__

    def no_ml(name, *a, **k):
        if name in ("fastembed", "sentence_transformers"):
            raise ImportError(name)
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_ml)
    assert c._load_embedder() is None


@pytest.mark.skipif(not _fastembed_available(), reason="fastembed not installed (opt-in `semantic` group)")
def test_fastembed_roundtrip(tmp_path):
    c._embedder = None  # reset singleton
    e = c._load_embedder()
    assert e is not None and e.backend == "fastembed"
    passages = e.embed_passages(["the cell's powerhouse is the mitochondria", "Q3 revenue rose 12%"])
    assert len(passages) == 2 and len(passages[0]) == c.EMBED_DIM
    q = e.embed_query("what powers a cell?")
    assert len(q) == c.EMBED_DIM
    # relevant passage must out-score the irrelevant one
    cos = lambda a, b: sum(x * y for x, y in zip(a, b))
    assert cos(q, passages[0]) > cos(q, passages[1])
