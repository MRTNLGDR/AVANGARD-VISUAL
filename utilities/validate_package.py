#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import py_compile
import subprocess
import sys
from pathlib import Path

REQUIRED = [
    "README.md", "QUICKSTART.md", "CHANGELOG.md", "LICENSE", "THIRD_PARTY_NOTICES.md",
    ".env.example", "docker-compose.yml", "Dockerfile", "install.ps1", "install.sh",
    "run.bat", "run.sh", "stop.bat", "stop.sh", "uninstall.ps1", "uninstall.sh",
    "source/backend/pyproject.toml", "source/backend/cinenode/api.py", "source/backend/cinenode/agent.py",
    "source/backend/cinenode/preflight.py", "source/backend/cinenode/providers/cloud.py",
    "source/backend/cinenode/engines/mesh.py", "source/backend/cinenode/frontend/index.html",
    "source/desktop/src-tauri/tauri.conf.json", "tests", "docs", "scripts",
    "vendor/opensources/manifest.json", "utilities/install-3d-engines.ps1",
    "utilities/install-3d-engines.sh", "utilities/install-comfyui.ps1", "utilities/install-comfyui.sh",
]
FORBIDDEN_SOURCE_MARKERS = ["TODO_IMPLEMENT_ME", "MOCK_SUCCESS", "FAKE_RESPONSE"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--run-smoke", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    failures: list[str] = []
    checks: list[dict] = []

    for rel in REQUIRED:
        exists = (root / rel).exists()
        checks.append({"check": "required", "path": rel, "ok": exists})
        if not exists:
            failures.append(f"missing:{rel}")

    for path in root.rglob("*.json"):
        try:
            json.loads(path.read_text(encoding="utf-8-sig"))
            checks.append({"check": "json", "path": str(path.relative_to(root)), "ok": True})
        except Exception as exc:
            failures.append(f"json:{path}:{exc}")

    for path in root.rglob("*.py"):
        if any(part in {".runtime", ".pytest_cache", "__pycache__"} for part in path.parts):
            continue
        try:
            py_compile.compile(str(path), doraise=True)
        except Exception as exc:
            failures.append(f"python:{path}:{exc}")

    app_js = root / "source" / "frontend" / "app.js"
    node = subprocess.run(["node", "--check", str(app_js)], capture_output=True, text=True) if shutil_which("node") else None
    if node and node.returncode:
        failures.append(f"javascript:{node.stderr}")

    for path in [root / "source", root / "scripts", root / "tests"]:
        for file in path.rglob("*") if path.exists() else []:
            if not file.is_file() or file.suffix.lower() not in {".py", ".js", ".ts", ".tsx", ".rs", ".sh", ".ps1"}:
                continue
            # The validator necessarily contains the marker names it searches for.
            # Exclude only this file; all product, installer and test sources remain scanned.
            if file.resolve() == Path(__file__).resolve():
                continue
            text = file.read_text(encoding="utf-8", errors="replace")
            for marker in FORBIDDEN_SOURCE_MARKERS:
                if marker in text:
                    failures.append(f"forbidden-marker:{marker}:{file.relative_to(root)}")

    audit_script = root / "scripts" / "audit_upstream.py"
    if audit_script.is_file():
        import importlib.util
        spec = importlib.util.spec_from_file_location("cinenode_package_audit", audit_script)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            supply_chain_report = module.scan_repository(root)
            checks.append({"check": "invisible-unicode", "ok": supply_chain_report["summary"]["critical"] == 0})
            if supply_chain_report["summary"]["critical"]:
                failures.append("supply-chain:hidden-unicode")

    if args.run_smoke and not failures:
        result = subprocess.run([sys.executable, str(root / "scripts" / "smoke_test.py"), "--root", str(root)], cwd=root)
        if result.returncode:
            failures.append("smoke-test")

    report = {"root": str(root), "status": "passed" if not failures else "failed", "failures": failures, "checks": len(checks)}
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0 if not failures else 1


def shutil_which(name: str) -> str | None:
    import shutil
    return shutil.which(name)


if __name__ == "__main__":
    raise SystemExit(main())
