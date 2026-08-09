from __future__ import annotations

from conftest import wait_for_job


def text_graph():
    return {
        "version": 1,
        "nodes": [
            {"id": "prompt", "type": "input.text", "position": {"x": 0, "y": 0}, "config": {"text": "Cena cinematográfica local"}},
            {"id": "preview", "type": "output.preview", "position": {"x": 260, "y": 0}, "config": {}},
        ],
        "edges": [{"id": "e1", "source": "prompt", "target": "preview"}],
        "metadata": {},
    }


def test_text_workflow_runs_end_to_end(client):
    project = client.post("/api/projects", json={"name": "Text pipeline", "description": "", "graph": text_graph()}).json()
    queued = client.post("/api/jobs", json={"project_id": project["id"]})
    assert queued.status_code == 202
    job = wait_for_job(client, queued.json()["id"])
    assert job["status"] == "SUCCEEDED"
    assert job["progress"] == 100
    assert job["result"]["terminal_results"][0]["text"] == "Cena cinematográfica local"
    assert job["result"]["assets"] == []


def test_missing_engine_fails_with_actionable_code(client):
    graph = {
        "version": 1,
        "nodes": [
            {"id": "prompt", "type": "input.text", "position": {"x": 0, "y": 0}, "config": {"text": "teste"}},
            {"id": "image", "type": "image.generate", "position": {"x": 240, "y": 0}, "config": {"engine": "sd_cpp", "profile_id": "z-image-turbo-fast", "width": 512, "height": 512, "steps": 1}},
        ],
        "edges": [{"id": "e", "source": "prompt", "target": "image"}],
        "metadata": {},
    }
    queued = client.post("/api/jobs", json={"graph": graph})
    assert queued.status_code == 202
    job = wait_for_job(client, queued.json()["id"])
    assert job["status"] == "FAILED"
    assert job["error_code"] == "ENGINE_BINARY_MISSING"
    assert "binário" in job["error_message"]


def test_cancel_queued_job(client, app):
    job = app.state.store.create_job(None, __import__('cinenode.schemas', fromlist=['WorkflowGraph']).WorkflowGraph.model_validate(text_graph()))
    response = client.post(f"/api/jobs/{job['id']}/cancel")
    assert response.status_code == 200
    assert response.json()["cancel_requested"] is True
