"""Fixed-argv CLI for CE host tools. Used by the Pi curator pack.

    python -m switchbay.ce_cli --workspace W --tool ce_wave_prime --input '{}'

Does not reimplement planner.py. Unknown tools fail closed.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _allowlist(raw: str | None) -> set[str] | None:
    text = (raw or "").strip()
    if not text:
        return None
    return {t.strip() for t in text.split(",") if t.strip()}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="switchbay.ce_cli")
    p.add_argument("--workspace", type=Path, required=True)
    p.add_argument("--tool", required=True)
    p.add_argument("--input", default="{}", help="JSON object of tool arguments")
    p.add_argument(
        "--allow-tools",
        default="",
        help="Comma-separated allowlist (overrides SWITCHBAY_PACKAGE_TOOLS).",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve the tool and print the call; do not execute.",
    )
    args = p.parse_args(argv)

    # Register CE tools via the rail registry.
    from switchbay import tools  # noqa: F401
    from switchbay.ce_tools import CE_TOOL_NAMES

    name = str(args.tool).strip()
    if name not in CE_TOOL_NAMES and name not in tools.REGISTRY:
        print(json.dumps({"ok": False, "error": f"unknown tool: {name}"}))
        return 2
    allowed = _allowlist(args.allow_tools) or _allowlist(
        os.environ.get("SWITCHBAY_PACKAGE_TOOLS"),
    )
    if allowed is not None and name not in allowed:
        print(json.dumps({
            "ok": False,
            "error": f"tool {name!r} is not on this package allowlist",
            "package_id": os.environ.get("SWITCHBAY_PACKAGE_ID") or "",
        }))
        return 2
    try:
        payload = json.loads(args.input) if args.input else {}
    except json.JSONDecodeError as exc:
        print(json.dumps({"ok": False, "error": f"bad --input: {exc}"}))
        return 2
    if not isinstance(payload, dict):
        print(json.dumps({"ok": False, "error": "--input must be a JSON object"}))
        return 2

    info = {
        "ok": True,
        "tool": name,
        "workspace": str(args.workspace.resolve()),
        "payload": payload,
    }
    if args.dry_run:
        info["dry_run"] = True
        print(json.dumps(info, default=str))
        return 0
    try:
        out = tools.execute(name, args.workspace.resolve(), payload)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"ok": False, "tool": name, "error": str(exc)[:400]}))
        return 1
    if isinstance(out, dict):
        info["result"] = out
        if out.get("ok") is False:
            info["ok"] = False
            print(json.dumps(info, default=str))
            return 1
    else:
        info["result"] = {"text": str(out)}
    print(json.dumps(info, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
