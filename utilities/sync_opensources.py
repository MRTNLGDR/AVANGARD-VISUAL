#!/usr/bin/env python3
"""Clone pinned upstreams into quarantine, audit, hash and atomically promote."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from audit_upstream import scan_repository


def run(*args: str, cwd: Path | None = None) -> None:
    subprocess.run(args, cwd=cwd, check=True)


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tracked_files(root: Path) -> list[str]:
    raw = subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
    return [item.decode("utf-8", "surrogateescape") for item in raw.split(b"\0") if item]


def promote(staging: Path, target: Path) -> None:
    old = target.with_name(target.name + ".previous")
    if old.exists():
        shutil.rmtree(old)
    if target.exists():
        target.rename(old)
    try:
        staging.rename(target)
    except Exception:
        if old.exists() and not target.exists():
            old.rename(target)
        raise
    if old.exists():
        shutil.rmtree(old)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--accept-wangp-license", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    base = project_root / "vendor" / "opensources"
    manifest_path = base / "manifest.json"
    upstream = base / "upstream"
    quarantine = base / "quarantine"
    licenses = base / "licenses"
    checksums = base / "checksums"
    audits = base / "audits"
    for path in (upstream, quarantine, licenses, checksums, audits):
        path.mkdir(parents=True, exist_ok=True)

    if not shutil.which("git"):
        raise SystemExit("git é obrigatório")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    lock = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "repositories": [],
    }

    for repo in manifest["repositories"]:
        if repo.get("requires_acceptance") and not args.accept_wangp_license:
            print(f"SKIP {repo['name']}: aceite explícito da licença necessário", flush=True)
            lock["repositories"].append({
                "id": repo["id"],
                "status": "SKIPPED_LICENSE_ACCEPTANCE",
                "expected_commit": repo["commit"],
            })
            continue

        target = upstream / repo["directory"]
        if target.exists() and not args.force:
            actual = subprocess.check_output(["git", "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
            checksum_file = checksums / f"{repo['id']}.sha256"
            audit_file = audits / f"{repo['id']}.json"
            if actual == repo["commit"] and checksum_file.is_file() and audit_file.is_file():
                print(f"UNCHANGED {repo['id']} {actual}", flush=True)
                lock["repositories"].append({
                    "id": repo["id"], "status": "UNCHANGED", "expected_commit": repo["commit"],
                    "actual_commit": actual, "path": str(target),
                })
                continue

        staging = quarantine / repo["directory"]
        if staging.exists():
            shutil.rmtree(staging)
        print(f"CLONE {repo['id']} -> quarentena", flush=True)
        run("git", "clone", "--recursive", "--no-single-branch", repo["url"], str(staging))
        run("git", "checkout", "--detach", repo["commit"], cwd=staging)
        run("git", "submodule", "update", "--init", "--recursive", cwd=staging)
        actual = subprocess.check_output(["git", "-C", str(staging), "rev-parse", "HEAD"], text=True).strip()
        if actual != repo["commit"]:
            raise SystemExit(f"Commit divergente em {repo['id']}: {actual}")

        audit = scan_repository(staging)
        audit_path = audits / f"{repo['id']}.json"
        audit_path.write_text(json.dumps(audit, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        if audit["summary"]["critical"]:
            print(f"REJECT {repo['id']}: Unicode invisível crítico; clone mantido em {staging}", file=sys.stderr)
            lock["repositories"].append({
                "id": repo["id"], "status": "REJECTED_SECURITY_AUDIT", "expected_commit": repo["commit"],
                "actual_commit": actual, "quarantine_path": str(staging), "audit": str(audit_path),
            })
            continue

        tracked = tracked_files(staging)
        lines: list[str] = []
        for rel in tracked:
            path = staging / rel
            if path.is_file():
                lines.append(f"{hash_file(path)}  {rel}")
        (checksums / f"{repo['id']}.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")

        license_source = next(
            (staging / name for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING") if (staging / name).is_file()),
            None,
        )
        if license_source:
            shutil.copy2(license_source, licenses / f"{repo['id']}-{license_source.name}")

        promote(staging, target)
        lock["repositories"].append({
            "id": repo["id"], "status": "CHECKED_OUT_AUDITED", "expected_commit": repo["commit"],
            "actual_commit": actual, "path": str(target), "files": len(lines), "audit": str(audit_path),
            "audit_status": audit["status"],
        })
        print(f"OK {repo['id']} {actual} ({len(lines)} arquivos)", flush=True)

    (base / "manifest.lock.json").write_text(json.dumps(lock, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    rejected = [item for item in lock["repositories"] if item["status"] == "REJECTED_SECURITY_AUDIT"]
    return 1 if rejected else 0


if __name__ == "__main__":
    raise SystemExit(main())
