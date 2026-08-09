from __future__ import annotations

import argparse
import asyncio
import json
import os
import platform
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from .api import create_app
from .backup import create_backup
from .config import AppConfig
from .database import Database
from .engines import EngineRegistry
from .governance import read_governance_snapshot, seed_governance
from .store import Store


def initialize(config: AppConfig) -> None:
    config.ensure_directories()
    db = Database(config.database)
    db.initialize()
    store = Store(db, config)
    store.initialize_defaults()
    seed_governance(db)


def _open_browser(url: str) -> None:
    for _ in range(80):
        try:
            with socket.create_connection(("127.0.0.1", int(url.rsplit(":", 1)[1])), timeout=0.2):
                webbrowser.open(url)
                return
        except OSError:
            time.sleep(0.25)


def run_server(config: AppConfig, open_browser: bool = True) -> int:
    initialize(config)
    pid_file = config.home / "cinenode.pid"
    pid_file.write_text(str(os.getpid()), encoding="utf-8")
    url = f"http://{config.host}:{config.port}"
    if open_browser:
        threading.Thread(target=_open_browser, args=(url,), daemon=True).start()
    app = create_app(config)
    try:
        uvicorn.run(app, host=config.host, port=config.port, log_level="info", access_log=True)
    finally:
        pid_file.unlink(missing_ok=True)
    return 0


async def doctor(config: AppConfig) -> dict:
    initialize(config)
    db = Database(config.database)
    store = Store(db, config)
    registry = EngineRegistry(store, config)
    return {
        "platform": platform.platform(),
        "python": sys.version,
        "paths": {"home": str(config.home), "database": str(config.database), "frontend": str(config.frontend_dir)},
        "database_integrity": db.scalar("PRAGMA integrity_check"),
        "governance": read_governance_snapshot(db)["summary"],
        "engines": await registry.status_all(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="cinenode")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    run = sub.add_parser("run")
    run.add_argument("--no-browser", action="store_true")
    sub.add_parser("doctor")
    backup = sub.add_parser("backup")
    backup.add_argument("--no-assets", action="store_true")
    backup.add_argument("--no-outputs", action="store_true")
    args = parser.parse_args(argv)
    config = AppConfig.from_env()
    if args.command == "init":
        initialize(config)
        print(json.dumps({"status": "initialized", "home": str(config.home), "database": str(config.database)}, ensure_ascii=False, indent=2))
        return 0
    if args.command == "run":
        return run_server(config, open_browser=not args.no_browser)
    if args.command == "doctor":
        print(json.dumps(asyncio.run(doctor(config)), ensure_ascii=False, indent=2))
        return 0
    if args.command == "backup":
        initialize(config)
        db = Database(config.database)
        print(json.dumps(create_backup(db, config, include_assets=not args.no_assets, include_outputs=not args.no_outputs), ensure_ascii=False, indent=2))
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
