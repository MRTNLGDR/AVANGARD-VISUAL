from __future__ import annotations

import zipfile
from pathlib import Path


def graph():
    return {"version": 1, "nodes": [], "edges": [], "metadata": {}}


def test_settings_patch_is_persistent(client):
    current = client.get("/api/settings").json()
    prefs = dict(current["app.preferences"])
    prefs["governance_poll_ms"] = 10000
    response = client.patch("/api/settings", json={"values": {"app.preferences": prefs}})
    assert response.status_code == 200
    assert client.get("/api/settings").json()["app.preferences"]["governance_poll_ms"] == 10000


def test_backup_contains_manifest_and_consistent_database(client):
    client.post("/api/projects", json={"name": "Backup project", "description": "", "graph": graph()})
    response = client.post("/api/backups", json={"include_assets": True, "include_outputs": True})
    assert response.status_code == 200
    result = response.json()
    path = Path(result["path"])
    assert path.is_file()
    assert len(result["sha256"]) == 64
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        assert "manifest.json" in names
        assert "database/cinenode.sqlite3" in names


def test_project_export(client):
    project = client.post("/api/projects", json={"name": "Export project", "description": "", "graph": graph()}).json()
    response = client.post(f"/api/projects/{project['id']}/export")
    assert response.status_code == 200
    path = Path(response.json()["path"])
    assert path.is_file()
    with zipfile.ZipFile(path) as archive:
        assert "project.json" in archive.namelist()


def test_backup_restore_replaces_database_and_preserves_original_state(client):
    original = client.post("/api/projects", json={"name": "Original", "description": "before", "graph": graph()}).json()
    backup = client.post("/api/backups", json={"include_assets": True, "include_outputs": True}).json()
    assert client.delete(f"/api/projects/{original['id']}").status_code == 204
    replacement = client.post("/api/projects", json={"name": "Replacement", "description": "after", "graph": graph()}).json()

    restored = client.post(
        "/api/backups/restore",
        json={"backup_path": backup["path"], "replace_existing": True},
    )
    assert restored.status_code == 200, restored.text
    projects = client.get("/api/projects").json()["items"]
    ids = {item["id"] for item in projects}
    assert original["id"] in ids
    assert replacement["id"] not in ids
    assert restored.json()["manifest"]["format"] == "avangard-cinenode-backup"
    assert Path(restored.json()["safety_backup"]["path"]).is_file()


def test_restore_rejects_zip_slip(client, config):
    import zipfile

    malicious = config.backups_dir / "malicious.zip"
    with zipfile.ZipFile(malicious, "w") as archive:
        archive.writestr("../escaped.txt", "blocked")
    response = client.post(
        "/api/backups/restore",
        json={"backup_path": str(malicious), "replace_existing": True},
    )
    assert response.status_code == 400
    assert "Unsafe path" in response.json()["error"]["message"]
    assert not (config.home.parent / "escaped.txt").exists()
