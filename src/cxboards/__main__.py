"""``cxboards serve`` (the app), ``cxboards mcp`` (stdio MCP), ``cxboards export`` (all snapshots)."""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cxboards")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve", help="run the web app + API on 127.0.0.1")
    sub.add_parser("mcp", help="run the MCP server over stdio")
    sub.add_parser("export", help="rewrite every board's Onyx snapshot")
    args = parser.parse_args(argv)

    if args.command == "serve":
        import uvicorn

        from .app import create_app
        from .config import load_config

        config = load_config()
        uvicorn.run(create_app(config), host="127.0.0.1", port=config.port, log_level="info")
    elif args.command == "mcp":
        from .mcp_server import run

        run()
    elif args.command == "export":
        from .config import load_config
        from .export import Exporter
        from .store import Store

        for path in Exporter(Store(load_config())).export_all():
            print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
