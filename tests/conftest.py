from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cinenode.api import create_app
from cinenode.config import AppConfig


@pytest.fixture()
def config(tmp_path: Path) -> AppConfig:
    home = tmp_path / "data"
    frontend = Path(__file__).resolve().parents[1] / "source" / "backend" / "cinenode" / "frontend"
    value = AppConfig(
        home=home,
        database=home / "cinenode.sqlite3",
        assets_dir=home / "assets",
        projects_dir=home / "projects",
        outputs_dir=home / "outputs",
        uploads_dir=home / "uploads",
        backups_dir=home / "backups",
        logs_dir=home / "logs",
        models_dir=home / "models",
        engines_dir=home / "engines",
        temp_dir=home / "tmp",
        frontend_dir=frontend,
        host="127.0.0.1",
        port=8787,
        max_upload_bytes=4 * 1024 * 1024,
        command_timeout_seconds=120,
        local_access_token="test-token",
        allow_shutdown_endpoint=False,
    )
    value.ensure_directories()
    return value


@pytest.fixture()
def app(config: AppConfig):
    return create_app(config)


@pytest.fixture()
def client(app):
    with TestClient(app) as value:
        yield value


def wait_for_job(client: TestClient, job_id: str, timeout: float = 12.0) -> dict:
    import time
    end = time.monotonic() + timeout
    last = None
    while time.monotonic() < end:
        response = client.get(f"/api/jobs/{job_id}")
        assert response.status_code == 200
        last = response.json()
        if last["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
            return last
        time.sleep(0.1)
    raise AssertionError(f"Job did not finish: {last}")
