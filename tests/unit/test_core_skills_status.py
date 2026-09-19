"""C1 combined core-skills status shape."""

from __future__ import annotations

from switchbay import core_skills


def test_status_shape(monkeypatch):
    from switchbay import ce_viewer_supervisor as ce
    from switchbay import okstratr_supervisor as oks

    monkeypatch.setattr(
        ce,
        "contract_slice",
        lambda _ws=None: {
            "state": "stopped",
            "url": "http://127.0.0.1:8766",
            "detail": "x",
        },
    )
    monkeypatch.setattr(
        oks,
        "contract_slice",
        lambda: {
            "state": "healthy",
            "url": "http://127.0.0.1:8767",
            "detail": "up",
        },
    )
    monkeypatch.setattr(
        ce,
        "wiki_build_slice",
        lambda: {"state": "idle", "pages": None, "detail": ""},
    )
    out = core_skills.status()
    assert set(out) == {"ce", "okstratr", "wiki_build"}
    assert out["ce"]["state"] == "stopped"
    assert out["okstratr"]["state"] == "healthy"
    assert out["wiki_build"]["state"] == "idle"
