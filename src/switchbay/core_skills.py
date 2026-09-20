"""Combined core-skills status (CE + okstratr + wiki_build).

Contract C1 shared status shape for UI / Herdr / CLI.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import ce_viewer_supervisor, okstratr_supervisor


def status(workspace: Path | None = None) -> dict[str, Any]:
    """Return the C1 status object."""
    ce = ce_viewer_supervisor.contract_slice(workspace)
    oks = okstratr_supervisor.contract_slice()
    wiki = ce_viewer_supervisor.wiki_build_slice()
    return {
        "ce": ce,
        "okstratr": oks,
        "wiki_build": wiki,
    }
