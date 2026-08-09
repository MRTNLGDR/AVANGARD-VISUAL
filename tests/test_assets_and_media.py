from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from PIL import Image

from conftest import wait_for_job


def test_upload_sanitizes_name_and_persists(client, config):
    content = b"hello"
    response = client.post("/api/assets/upload", files={"file": ("../../evil?.txt", content, "text/plain")})
    assert response.status_code == 201
    asset = response.json()
    assert ".." not in asset["original_name"]
    path = Path(asset["path"])
    assert path.is_file()
    assert path.read_bytes() == content
    assert path.resolve().is_relative_to(config.uploads_dir.resolve())
    served = client.get(f"/media/{asset['id']}")
    assert served.status_code == 200
    assert served.content == content


def test_upload_limit_is_enforced(client):
    response = client.post("/api/assets/upload", files={"file": ("large.bin", b"x" * (4 * 1024 * 1024 + 1), "application/octet-stream")})
    assert response.status_code == 413


@pytest.mark.media
@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg unavailable")
def test_real_ffmpeg_resize_pipeline(client, app, config):
    source = config.uploads_dir / "source.png"
    Image.new("RGB", (32, 24), (30, 120, 220)).save(source)
    asset = app.state.store.add_asset(source, "image", original_name="source.png", mime_type="image/png")
    graph = {
        "version": 1,
        "nodes": [
            {"id": "input", "type": "input.asset", "position": {"x": 0, "y": 0}, "config": {"asset_id": asset["id"]}},
            {"id": "resize", "type": "image.resize", "position": {"x": 220, "y": 0}, "config": {"width": 64, "height": 48}},
            {"id": "preview", "type": "output.preview", "position": {"x": 440, "y": 0}, "config": {}},
        ],
        "edges": [
            {"id": "e1", "source": "input", "target": "resize"},
            {"id": "e2", "source": "resize", "target": "preview"},
        ],
        "metadata": {},
    }
    queued = client.post("/api/jobs", json={"graph": graph})
    job = wait_for_job(client, queued.json()["id"], timeout=20)
    assert job["status"] == "SUCCEEDED", job
    output_path = Path(job["result"]["terminal_results"][0]["path"])
    assert output_path.is_file()
    with Image.open(output_path) as image:
        assert image.size == (64, 48)
