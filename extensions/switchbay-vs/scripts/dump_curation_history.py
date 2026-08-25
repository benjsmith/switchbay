#!/usr/bin/env python3
"""Print the workspace curation-history JSON (cache hit or rebuild).

Used by the VS Code Graph webview replay button. Same payload as
``GET /api/curation/history`` in the PWA daemon.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: dump_curation_history.py <workspace>", file=sys.stderr)
        return 2
    ws = Path(sys.argv[1]).expanduser().resolve()
    if not ws.is_dir():
        print(f"not a directory: {ws}", file=sys.stderr)
        return 1
    from switchbay.curation_history import read_or_build

    data = asyncio.run(read_or_build(ws))
    json.dump(data or {"duration": 15.0, "events": [], "source": "missing"}, sys.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
