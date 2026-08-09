from __future__ import annotations

import time

from fastapi.testclient import TestClient

from cinenode.api import create_app
from cinenode.schemas import WorkflowGraph


def text_graph() -> WorkflowGraph:
    return WorkflowGraph.model_validate({
        "version": 1,
        "nodes": [
            {"id": "prompt", "type": "input.text", "position": {"x": 0, "y": 0}, "config": {"text": "retomar"}},
            {"id": "preview", "type": "output.preview", "position": {"x": 200, "y": 0}, "config": {}},
        ],
        "edges": [{"id": "e", "source": "prompt", "target": "preview"}],
        "metadata": {},
    })


def test_restart_marks_running_failed_and_resumes_queued(config):
    first_app = create_app(config)
    with TestClient(first_app):
        interrupted = first_app.state.store.create_job(None, text_graph())
        first_app.state.store.update_job(interrupted["id"], status="RUNNING", started_at="2026-08-06T00:00:00Z")
        queued = first_app.state.store.create_job(None, text_graph())

    second_app = create_app(config)
    with TestClient(second_app) as client:
        recovered = client.get(f"/api/jobs/{interrupted['id']}").json()
        assert recovered["status"] == "FAILED"
        assert recovered["error_code"] == "PROCESS_INTERRUPTED"
        deadline = time.monotonic() + 5
        resumed = None
        while time.monotonic() < deadline:
            resumed = client.get(f"/api/jobs/{queued['id']}").json()
            if resumed["status"] in {"SUCCEEDED", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.05)
        assert resumed is not None
        assert resumed["status"] == "SUCCEEDED", resumed
        assert resumed["result"]["terminal_results"][0]["text"] == "retomar"
