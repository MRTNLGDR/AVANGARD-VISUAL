from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path
from typing import Any

from .config import AppConfig
from .database import Database
from .util import new_id, sha256_file, utc_now


class BackupError(RuntimeError):
    pass


def _safe_zip_member(member: zipfile.ZipInfo) -> None:
    path = Path(member.filename)
    if path.is_absolute() or ".." in path.parts:
        raise BackupError(f"Unsafe path in backup: {member.filename}")


def create_backup(
    db: Database,
    config: AppConfig,
    *,
    include_assets: bool = True,
    include_outputs: bool = True,
) -> dict[str, Any]:
    config.backups_dir.mkdir(parents=True, exist_ok=True)
    stamp = utc_now().replace(":", "").replace("-", "").replace(".", "")
    target = config.backups_dir / f"cinenode-backup-{stamp}-{new_id('bkp')[-8:]}.zip"
    with tempfile.TemporaryDirectory(prefix="cinenode-backup-", dir=config.temp_dir) as temp_name:
        temp = Path(temp_name)
        db_copy = temp / "cinenode.sqlite3"
        # sqlite3.Connection's context manager commits/rolls back but does not
        # close the handle. Explicit closing is required on Windows before the
        # temporary directory can be removed.
        with closing(sqlite3.connect(config.database)) as source, closing(sqlite3.connect(db_copy)) as destination:
            source.backup(destination)
        manifest = {
            "format": "avangard-cinenode-backup",
            "version": 1,
            "created_at": utc_now(),
            "database_sha256": sha256_file(db_copy),
            "include_assets": include_assets,
            "include_outputs": include_outputs,
        }
        (temp / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as archive:
            archive.write(db_copy, "database/cinenode.sqlite3")
            archive.write(temp / "manifest.json", "manifest.json")
            for enabled, directory, prefix in (
                (include_assets, config.assets_dir, "assets"),
                (include_assets, config.uploads_dir, "uploads"),
                (include_outputs, config.outputs_dir, "outputs"),
            ):
                if not enabled or not directory.exists():
                    continue
                for path in directory.rglob("*"):
                    if path.is_file():
                        archive.write(path, str(Path(prefix) / path.relative_to(directory)))
    return {"path": str(target), "sha256": sha256_file(target), "size_bytes": target.stat().st_size, "created_at": manifest["created_at"]}


def restore_backup(db: Database, config: AppConfig, backup_path: Path, *, replace_existing: bool = False) -> dict[str, Any]:
    backup_path = backup_path.expanduser().resolve()
    if not backup_path.is_file():
        raise BackupError(f"Backup not found: {backup_path}")
    if not replace_existing:
        project_count = int(db.scalar("SELECT COUNT(*) FROM projects") or 0)
        asset_count = int(db.scalar("SELECT COUNT(*) FROM assets") or 0)
        if project_count or asset_count:
            raise BackupError("Current database is not empty; enable replace_existing explicitly")
    with tempfile.TemporaryDirectory(prefix="cinenode-restore-", dir=config.temp_dir) as temp_name:
        staging = Path(temp_name)
        with zipfile.ZipFile(backup_path, "r") as archive:
            for member in archive.infolist():
                _safe_zip_member(member)
            archive.extractall(staging)
        manifest_path = staging / "manifest.json"
        restored_db = staging / "database" / "cinenode.sqlite3"
        if not manifest_path.is_file() or not restored_db.is_file():
            raise BackupError("Backup does not contain the required manifest/database")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if manifest.get("format") != "avangard-cinenode-backup":
            raise BackupError("Unsupported backup format")
        expected = manifest.get("database_sha256")
        if expected and sha256_file(restored_db) != expected:
            raise BackupError("Backup database checksum mismatch")
        with closing(sqlite3.connect(restored_db)) as connection:
            check = connection.execute("PRAGMA integrity_check").fetchone()[0]
            if check != "ok":
                raise BackupError(f"Restored database failed integrity_check: {check}")
        safety = create_backup(db, config, include_assets=False, include_outputs=False)
        # SQLite WAL files belong to the current database generation. Leaving them
        # beside a replaced main file can replay newer pages over the restored copy.
        staged_database = config.database.with_name(f".{config.database.name}.restore.tmp")
        shutil.copy2(restored_db, staged_database)
        with staged_database.open("rb+") as stream:
            stream.flush()
            os.fsync(stream.fileno())
        for suffix in ("-wal", "-shm"):
            config.database.with_name(config.database.name + suffix).unlink(missing_ok=True)
        os.replace(staged_database, config.database)
        for prefix, directory in (("assets", config.assets_dir), ("uploads", config.uploads_dir), ("outputs", config.outputs_dir)):
            source = staging / prefix
            if source.exists():
                if replace_existing:
                    shutil.rmtree(directory, ignore_errors=True)
                directory.mkdir(parents=True, exist_ok=True)
                shutil.copytree(source, directory, dirs_exist_ok=True)
    db.initialize()
    return {"restored_from": str(backup_path), "safety_backup": safety, "manifest": manifest}


def export_project(db: Database, config: AppConfig, project_id: str) -> dict[str, Any]:
    project = db.query_one("SELECT * FROM projects WHERE id=?", (project_id,))
    if not project:
        raise BackupError("Project not found")
    assets = db.query("SELECT * FROM assets WHERE project_id=? ORDER BY created_at", (project_id,))
    jobs = db.query("SELECT * FROM jobs WHERE project_id=? ORDER BY created_at", (project_id,))
    target = config.backups_dir / f"project-{project_id}-{utc_now().replace(':','')}.zip"
    payload = {"format": "avangard-cinenode-project", "version": 1, "project": project, "jobs": jobs, "assets": assets, "exported_at": utc_now()}
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
        archive.writestr("project.json", json.dumps(payload, ensure_ascii=False, indent=2))
        for asset in assets:
            path = Path(asset["path"])
            if path.is_file():
                archive.write(path, str(Path("assets") / asset["id"] / path.name))
    return {"path": str(target), "sha256": sha256_file(target), "size_bytes": target.stat().st_size}
