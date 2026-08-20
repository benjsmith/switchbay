#!/usr/bin/env python3
"""Fail if *launchers* in a staged payload still invoke package managers.

Source under src/ still contains gated helpers (they no-op when the
flag is off). Harvest looks at what endpoints actually *run*: serve
scripts, plists, task XML, cmd/ps1.
"""

from __future__ import annotations

import sys
from pathlib import Path

NEEDLES = (
    b"uv python install",
    b"npx skills add",
    b"setup.sh",
    b"curl -LsSf https://astral.sh/uv/install.sh",
    b"taskkill /IM python.exe",
)

GLOBS = (
    "serve.sh", "serve.cmd",
    "**/*.plist", "**/*.cmd", "**/*.ps1", "**/*.xml",
)


def main(root: Path) -> int:
    hits: list[str] = []
    seen: set[Path] = set()
    for g in GLOBS:
        for p in root.glob(g):
            if not p.is_file() or p in seen:
                continue
            seen.add(p)
            data = p.read_bytes()
            for n in NEEDLES:
                if n in data:
                    hits.append(f"{p.relative_to(root)}: {n.decode()}")
    if hits:
        print("harvest FAILED — launchers still contain:")
        for h in hits:
            print(" ", h)
        return 1
    print(f"harvest ok ({root})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1] if len(sys.argv) > 1 else ".")))
