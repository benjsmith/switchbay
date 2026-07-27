"""CLI entrypoint: `switchbay serve [--workspace PATH] [--port N]`."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import daemon


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="switchbay")
    sub = parser.add_subparsers(dest="cmd", required=True)

    serve = sub.add_parser("serve", help="Run the local daemon.")
    serve.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="Workspace folder (default: cwd).",
    )
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--host", default="127.0.0.1")

    svc = sub.add_parser(
        "service",
        help="Manage the always-on per-user OS service (launchd / "
             "systemd --user / Windows Scheduled Task).",
    )
    svc.add_argument(
        "action",
        choices=("install", "uninstall", "start", "stop", "restart", "status"),
    )

    args = parser.parse_args(argv)

    if args.cmd == "serve":
        return daemon.run(workspace=args.workspace.resolve(), host=args.host, port=args.port)
    if args.cmd == "service":
        from . import service
        return service.run(args.action)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
