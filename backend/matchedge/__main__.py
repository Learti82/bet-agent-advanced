"""Command line: ``python -m matchedge serve|import [--local PATH]|settle``."""
from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="matchedge", description="MatchEdge Local")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("serve", help="Run the local web app")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--open", action="store_true", help="Open the app in the default browser once started")
    i = sub.add_parser("import", help="Download and import the Open-Matchday dataset")
    i.add_argument("--local", help="Import from a local clone of the open-matchday repository instead")
    sub.add_parser("settle", help="Settle pending predictions against imported results")
    args = p.parse_args(argv)

    if args.cmd == "serve":
        import uvicorn
        from .main import create_app
        if args.host not in ("127.0.0.1", "localhost", "::1"):
            print(f"Warning: binding to {args.host} exposes your private data on the network.", file=sys.stderr)
        app = create_app()
        if args.open:
            import threading
            import webbrowser
            threading.Timer(1.5, webbrowser.open, [f"http://127.0.0.1:{args.port}"]).start()
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
        return 0
    from .db import Database
    db = Database()
    if args.cmd == "import":
        from pathlib import Path
        from .importer import import_from_directory, run_import
        rep = import_from_directory(db, Path(args.local)) if args.local else run_import(db)
        print(f"Imported {rep.competitions} competitions: {rep.results} results, {rep.fixtures} fixtures, "
              f"{rep.snapshot_prices} snapshot prices (method {rep.method}, dataset built {rep.generated_utc}).")
        for w in rep.warnings[:20]:
            print("  warning:", w)
        from .main import run_history_import
        print("Historical seasons (football-data.co.uk):", run_history_import(db))
        from .engine.tracking import auto_settle
        print("Settlement:", auto_settle(db))
        return 0
    if args.cmd == "settle":
        from .engine.tracking import auto_settle
        print(auto_settle(db))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
