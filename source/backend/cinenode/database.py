from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence


MIGRATIONS: list[tuple[int, str]] = [
    (
        1,
        r"""
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );

        CREATE TABLE IF NOT EXISTS projects (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            graph_json TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY,
            project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
            status TEXT NOT NULL CHECK(status IN ('QUEUED','RUNNING','SUCCEEDED','FAILED','CANCELLED')),
            progress REAL NOT NULL DEFAULT 0 CHECK(progress >= 0 AND progress <= 100),
            current_node_id TEXT,
            graph_json TEXT NOT NULL,
            result_json TEXT,
            error_code TEXT,
            error_message TEXT,
            cancel_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancel_requested IN (0,1)),
            created_at TEXT NOT NULL,
            started_at TEXT,
            finished_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_jobs_created_at ON jobs(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);

        CREATE TABLE IF NOT EXISTS assets (
            id TEXT PRIMARY KEY,
            project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
            job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
            kind TEXT NOT NULL,
            path TEXT NOT NULL UNIQUE,
            original_name TEXT,
            mime_type TEXT,
            size_bytes INTEGER NOT NULL DEFAULT 0,
            metadata_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_assets_created_at ON assets(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_assets_project ON assets(project_id);

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS governance_tasks (
            id TEXT PRIMARY KEY,
            module_id TEXT NOT NULL,
            module_title TEXT NOT NULL,
            category TEXT NOT NULL,
            title TEXT NOT NULL,
            source_path TEXT NOT NULL,
            source_line INTEGER NOT NULL DEFAULT 1,
            status TEXT NOT NULL CHECK(status IN ('PENDING','DONE')),
            priority TEXT NOT NULL DEFAULT 'MEDIUM',
            severity TEXT NOT NULL DEFAULT 'LOW',
            evidence_json TEXT NOT NULL DEFAULT '[]',
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_governance_tasks_module ON governance_tasks(module_id);
        CREATE INDEX IF NOT EXISTS idx_governance_tasks_status ON governance_tasks(status);

        CREATE TABLE IF NOT EXISTS governance_alerts (
            id TEXT PRIMARY KEY,
            severity TEXT NOT NULL CHECK(severity IN ('LOW','MEDIUM','HIGH','CRITICAL')),
            status TEXT NOT NULL CHECK(status IN ('OPEN','RESOLVED')),
            kind TEXT NOT NULL,
            fact TEXT NOT NULL,
            action TEXT NOT NULL,
            module_id TEXT NOT NULL,
            evidence_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS governance_changes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            release TEXT NOT NULL,
            category TEXT NOT NULL,
            description TEXT NOT NULL,
            source_line INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS governance_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            level TEXT NOT NULL CHECK(level IN ('INFO','WARN','ERROR')),
            event TEXT NOT NULL,
            detail_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_governance_logs_created ON governance_logs(created_at DESC);

        CREATE TABLE IF NOT EXISTS governance_documents (
            name TEXT PRIMARY KEY,
            link TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS audit_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            actor TEXT NOT NULL,
            action TEXT NOT NULL,
            target_type TEXT,
            target_id TEXT,
            detail_json TEXT NOT NULL DEFAULT '{}'
        );
        """,
    ),
    (
        2,
        r"""
        CREATE TABLE IF NOT EXISTS engine_checks (
            engine_id TEXT PRIMARY KEY,
            available INTEGER NOT NULL CHECK(available IN (0,1)),
            version TEXT,
            detail TEXT NOT NULL,
            checked_at TEXT NOT NULL
        );
        """,
    ),
]


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._migration_lock = threading.Lock()

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=30,
            isolation_level=None,
            check_same_thread=False,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    @contextmanager
    def connection(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            yield connection
        finally:
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    def initialize(self) -> None:
        with self._migration_lock, self.transaction() as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations "
                "(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT "
                "(strftime('%Y-%m-%dT%H:%M:%fZ','now')))"
            )
            applied = {
                int(row["version"])
                for row in connection.execute("SELECT version FROM schema_migrations")
            }
            for version, sql in MIGRATIONS:
                if version in applied:
                    continue
                connection.executescript(sql)
                connection.execute(
                    "INSERT INTO schema_migrations(version) VALUES (?)", (version,)
                )

    def execute(self, sql: str, params: Sequence[Any] = ()) -> int:
        with self.transaction() as connection:
            cursor = connection.execute(sql, params)
            return cursor.rowcount

    def executescript(self, sql: str) -> None:
        with self.transaction() as connection:
            connection.executescript(sql)

    def query(self, sql: str, params: Sequence[Any] = ()) -> list[dict[str, Any]]:
        with self.connection() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def query_one(self, sql: str, params: Sequence[Any] = ()) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(sql, params).fetchone()
            return dict(row) if row is not None else None

    def scalar(self, sql: str, params: Sequence[Any] = ()) -> Any:
        with self.connection() as connection:
            row = connection.execute(sql, params).fetchone()
            return row[0] if row is not None else None

    @staticmethod
    def dump_json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def load_json(value: str | None, default: Any = None) -> Any:
        if value is None:
            return default
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
