from __future__ import annotations


def test_database_initialized_and_integrity(app, client):
    assert app.state.db.scalar("PRAGMA integrity_check") == "ok"
    versions = app.state.db.query("SELECT version FROM schema_migrations ORDER BY version")
    assert [item["version"] for item in versions] == [1, 2]
    assert client.get("/api/health").json()["status"] == "ok"


def test_governance_contract_is_real_and_complete(client):
    response = client.get("/api/governance/snapshot")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert set(payload) == {"generatedAt", "state", "summary", "modules", "tasks", "alerts", "changelog", "logs", "documents"}
    assert payload["state"] in {"READY", "DEGRADED", "EMPTY"}
    assert payload["summary"]["totalTasks"] == len(payload["tasks"])
    assert payload["summary"]["doneTasks"] + payload["summary"]["pendingTasks"] == payload["summary"]["totalTasks"]
    assert any(item["id"] == "GOV-001" for item in payload["tasks"])


def test_governance_task_update_persists(client):
    before = client.get("/api/governance/snapshot").json()
    task = next(item for item in before["tasks"] if item["id"] == "MODEL-001")
    response = client.patch("/api/governance/tasks/MODEL-001", json={"status": "DONE", "evidence": {"test": True}})
    assert response.status_code == 200
    after = response.json()
    updated = next(item for item in after["tasks"] if item["id"] == "MODEL-001")
    assert updated["status"] == "DONE"
    again = client.get("/api/governance/snapshot").json()
    assert next(item for item in again["tasks"] if item["id"] == "MODEL-001")["status"] == "DONE"
