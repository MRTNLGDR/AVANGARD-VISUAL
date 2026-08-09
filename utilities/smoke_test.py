#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def request(url: str, method: str = "GET", payload: dict | None = None) -> tuple[int, dict | str]:
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as response:
        raw = response.read().decode()
        try:
            return response.status, json.loads(raw)
        except json.JSONDecodeError:
            return response.status, raw


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    port = free_port()
    with tempfile.TemporaryDirectory(prefix="cinenode-smoke-") as temp:
        env = os.environ.copy()
        env.update({
            "PYTHONPATH": str(root / "source" / "backend"),
            "CINENODE_HOME": str(Path(temp) / "data"),
            "CINENODE_HOST": "127.0.0.1",
            "CINENODE_PORT": str(port),
        })
        log_path = Path(temp) / "server.log"
        with log_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-m", "cinenode", "run", "--no-browser"],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError(f"Server exited early ({process.returncode})\n{log_path.read_text(errors='replace')}")
                try:
                    status, body = request(base + "/api/health")
                    if status == 200 and isinstance(body, dict) and body.get("status") == "ok":
                        break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                raise RuntimeError("Server did not become ready")

            _, project = request(base + "/api/projects", "POST", {
                "name": "Smoke Test",
                "description": "Package smoke",
                "graph": {"version": 1, "nodes": [], "edges": [], "metadata": {}},
            })
            _, validation = request(base + "/api/workflows/validate", "POST", {
                "version": 1,
                "nodes": [{"id": "text-1", "type": "input.text", "position": {"x": 10, "y": 20}, "config": {"text": "cinematic"}}],
                "edges": [],
                "metadata": {},
            })
            _, governance = request(base + "/api/governance/snapshot")
            if not validation.get("valid"):
                raise RuntimeError(f"Graph validation failed: {validation}")
            if not governance.get("summary") or not governance.get("modules"):
                raise RuntimeError("Governance snapshot invalid")
            report = {
                "status": "passed",
                "base_url": base,
                "project_id": project["id"],
                "governance_state": governance["state"],
                "tasks": governance["summary"]["totalTasks"],
            }
            print(json.dumps(report, indent=2, ensure_ascii=False))
            return 0
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
