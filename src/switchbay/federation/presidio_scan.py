"""Presidio scan for a public write.

The packages are optional (``presidio`` dependency group). A missing
install is not a scan. A failed analyzer is not a scan. Only an
``analyze`` call that returns marks the text scanned.
"""

from __future__ import annotations

from typing import Any

_ENGINE: Any = None
_FAILED = False


def installed() -> bool:
    try:
        import presidio_analyzer  # noqa: F401
    except ImportError:
        return False
    return True


def _engine() -> Any:
    global _ENGINE, _FAILED
    if _ENGINE is not None:
        return _ENGINE
    if _FAILED:
        return None
    from presidio_analyzer import AnalyzerEngine
    try:
        _ENGINE = AnalyzerEngine()
    except Exception:
        _FAILED = True
        return None
    return _ENGINE


def scan(text: str) -> dict[str, Any]:
    """Return ``{scanned, entities}``. ``scanned`` is false when no analysis ran."""
    if _ENGINE is not None:
        engine = _ENGINE
    elif not installed():
        return {"scanned": False, "entities": [], "reason": "presidio not installed"}
    else:
        engine = _engine()
        if engine is None:
            return {"scanned": False, "entities": [], "reason": "presidio analyzer failed to load"}
    try:
        results = engine.analyze(text=text or "", language="en")
    except Exception as exc:
        return {"scanned": False, "entities": [], "reason": str(exc)}
    entities = []
    for item in results or []:
        kind = str(getattr(item, "entity_type", "") or "")
        if kind and kind not in entities:
            entities.append(kind)
    return {"scanned": True, "entities": entities}


def set_engine(engine: Any) -> None:
    """Tests inject an analyzer. ``None`` restores the real one."""
    global _ENGINE, _FAILED
    _ENGINE = engine
    _FAILED = False
