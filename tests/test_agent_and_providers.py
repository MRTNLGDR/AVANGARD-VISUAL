from __future__ import annotations

import io
import json
import os
from pathlib import Path

import httpx
import pytest
from PIL import Image

from cinenode.engines.common import EngineExecutionError
from cinenode.providers.cloud import FreepikProvider, TripoCloudProvider


def _png_bytes(rgb: tuple[int, int, int]) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (32, 24), rgb).save(stream, format="PNG")
    return stream.getvalue()


def _upload_image(client, name: str, rgb: tuple[int, int, int]) -> dict:
    response = client.post("/api/assets/upload", files={"file": (name, _png_bytes(rgb), "image/png")})
    assert response.status_code == 201, response.text
    return response.json()


def test_node_catalog_covers_agent_multiref_flf_and_3d(client):
    items = client.get("/api/nodes/catalog").json()["items"]
    types = {item["type"] for item in items}
    assert len(types) >= 24
    assert {
        "agent.director", "vision.analyze", "input.references", "image.edit",
        "video.first_last", "video.reference", "mesh.generate", "mesh.export",
    }.issubset(types)


def test_agent_builds_real_start_end_graph_with_local_flf_profile(client):
    start = _upload_image(client, "start.png", (10, 40, 90))
    end = _upload_image(client, "end.png", (90, 40, 10))
    response = client.post(
        "/api/agent/plan",
        json={
            "brief": "Criar um plano contínuo começando no primeiro quadro e terminando exatamente no segundo.",
            "target": "video",
            "references": [
                {"asset_id": start["id"], "role": "start_frame", "weight": 1, "note": "início"},
                {"asset_id": end["id"], "role": "end_frame", "weight": 1, "note": "fim"},
            ],
            "provider": "auto",
            "local_first": True,
            "use_llm": False,
            "planner_mode": "rules",
            "output_resolution": "preview",
            "create_project": True,
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["validation"]["valid"] is True
    assert payload["decisions"]["provider"] == "local.sd_cpp"
    by_id = {node["id"]: node for node in payload["graph"]["nodes"]}
    video = next(node for node in by_id.values() if node["type"] == "video.first_last")
    assert video["config"]["profile_id"] == "wan21-flf2v-14b-720p-q4"
    handles = {(edge["source"], edge["target_handle"]) for edge in payload["graph"]["edges"] if edge["target"] == video["id"]}
    assert ("start-frame", "start_frame") in handles
    assert ("end-frame", "end_frame") in handles
    assert payload["project"]["graph"] == payload["graph"]


def test_agent_uses_image_edit_for_single_reference_and_cloud_first_when_requested(client):
    image = _upload_image(client, "subject.png", (30, 80, 120))
    local = client.post(
        "/api/agent/plan",
        json={
            "brief": "Transformar a foto preservando a pessoa.",
            "target": "image",
            "references": [{"asset_id": image["id"], "role": "character"}],
            "local_first": True,
            "use_llm": False,
            "planner_mode": "rules",
            "output_resolution": "preview",
        },
    )
    assert local.status_code == 200, local.text
    local_payload = local.json()
    assert local_payload["decisions"]["provider"] == "local.sd_cpp"
    assert local_payload["validation"]["valid"] is True
    edit = next(node for node in local_payload["graph"]["nodes"] if node["type"] == "image.edit")
    assert any(
        edge["target"] == edit["id"] and edge["target_handle"] == "image"
        for edge in local_payload["graph"]["edges"]
    )

    cloud = client.post(
        "/api/agent/plan",
        json={
            "brief": "Criar uma imagem publicitária.",
            "target": "image",
            "references": [],
            "local_first": False,
            "use_llm": False,
            "planner_mode": "rules",
            "output_resolution": "preview",
        },
    )
    assert cloud.status_code == 200, cloud.text
    assert cloud.json()["decisions"]["provider"] == "cloud.freepik"


def test_agent_llm_plan_changes_film_topology_but_builder_remains_valid(client, app, monkeypatch):
    async def fake_plan(*args, **kwargs):
        return {
            "shot_count": 2,
            "direction": "Dois planos complementares.",
            "continuity_rules": ["mesmo personagem"],
            "camera_plan": ["plano geral", "close"],
            "model": "fake-local-model",
        }

    monkeypatch.setattr(app.state.registry, "plan_intent", fake_plan)
    response = client.post(
        "/api/agent/plan",
        json={
            "brief": "Filme curto de produto em dois planos.",
            "target": "film",
            "local_first": True,
            "use_llm": True,
            "planner_mode": "llm",
            "output_resolution": "preview",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["decisions"]["planner"] == "ollama-json+validated-builder"
    assert payload["decisions"]["llm_plan"]["shot_count"] == 2
    videos = [node for node in payload["graph"]["nodes"] if node["type"] == "video.generate"]
    assert len(videos) == 2
    assert payload["validation"]["valid"] is True


def test_multiview_3d_plan_preserves_roles_and_requires_explicit_local_workflow(client):
    front = _upload_image(client, "front.png", (100, 20, 20))
    back = _upload_image(client, "back.png", (20, 20, 100))
    response = client.post(
        "/api/agent/plan",
        json={
            "brief": "Reconstruir o objeto em 3D texturizado.",
            "target": "3d",
            "references": [
                {"asset_id": front["id"], "role": "front"},
                {"asset_id": back["id"], "role": "back"},
            ],
            "local_first": True,
            "use_llm": False,
            "planner_mode": "rules",
            "output_resolution": "preview",
        },
    )
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["decisions"]["provider"] == "local.comfyui"
    refs = next(node for node in payload["graph"]["nodes"] if node["type"] == "input.references")
    assert [item["role"] for item in refs["config"]["references"]] == ["front", "back"]
    assert any(node["type"] == "mesh.generate" for node in payload["graph"]["nodes"])


def test_cloud_provider_invoke_without_secret_fails_explicitly(client, monkeypatch):
    monkeypatch.delenv("FREEPIK_API_KEY", raising=False)
    current = client.get("/api/settings").json()
    providers = current["providers"]
    providers["cloud.freepik"]["enabled"] = True
    patched = client.patch("/api/settings", json={"values": {"providers": providers}})
    assert patched.status_code == 200
    response = client.post(
        "/api/providers/invoke",
        json={
            "provider_id": "cloud.freepik",
            "operation": "image",
            "prompt": "teste",
            "references": [],
            "parameters": {},
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PROVIDER_API_KEY_MISSING"


@pytest.mark.asyncio
async def test_freepik_start_end_contract_sends_image_and_image_tail(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("FREEPIK_API_KEY", "test-key")
    start = tmp_path / "start.png"
    end = tmp_path / "end.png"
    start.write_bytes(_png_bytes((1, 2, 3)))
    end.write_bytes(_png_bytes((4, 5, 6)))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST":
            return httpx.Response(200, json={"data": {"task_id": "task-1"}})
        return httpx.Response(200, json={"data": {"status": "COMPLETED", "generated": ["https://example.invalid/result.mp4"]}})

    transport = httpx.MockTransport(handler)

    class TestProvider(FreepikProvider):
        def client(self, headers):
            return httpx.AsyncClient(headers=headers, transport=transport)

        async def materialize(self, payload, output_path):
            return {"path": str(output_path), "provider_payload": payload}

    provider = TestProvider({"base_url": "https://api.example/v1/ai", "poll_interval_seconds": 0.01})
    result = await provider.invoke(
        "video", "camera move", "", [
            {"path": str(start), "role": "start_frame"},
            {"path": str(end), "role": "end_frame"},
        ], tmp_path / "out.mp4", {"duration": 5},
    )
    assert result["path"].endswith("out.mp4")
    body = json.loads(requests[0].content)
    assert body["image"].startswith("data:image/png;base64,")
    assert body["image_tail"].startswith("data:image/png;base64,")
    assert requests[0].url.path.endswith("/image-to-video/kling-std")


@pytest.mark.asyncio
async def test_tripo_v2_multiview_contract_uses_front_left_back_right_slots(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("TRIPO_API_KEY", "test-key")
    files = {}
    for role, color in (("front", (1, 0, 0)), ("back", (0, 0, 1))):
        path = tmp_path / f"{role}.png"
        path.write_bytes(_png_bytes(color))
        files[role] = path
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "POST" and request.url.path.endswith("/task"):
            return httpx.Response(200, json={"code": 0, "data": {"task_id": "t-3d"}})
        if request.method == "GET":
            return httpx.Response(200, json={"code": 0, "data": {"status": "success", "output": {"pbr_model": "https://example.invalid/model.glb"}}})
        raise AssertionError(str(request.url))

    transport = httpx.MockTransport(handler)

    class TestProvider(TripoCloudProvider):
        def client(self, headers):
            return httpx.AsyncClient(headers=headers, transport=transport)

        async def _upload(self, client, path):
            return {"type": "png", "file_token": f"token-{path.stem}"}

    async def fake_download(url, output_path, **kwargs):
        output_path.write_bytes(b"glTF-test")
        return {"path": str(output_path), "size_bytes": output_path.stat().st_size}

    monkeypatch.setattr("cinenode.providers.cloud.download_output", fake_download)
    provider = TestProvider({"base_url": "https://api.tripo3d.ai/v2/openapi", "poll_interval_seconds": 0.01})
    output = tmp_path / "model.glb"
    result = await provider.invoke_mesh(
        "object", "", [
            {"path": str(files["front"]), "role": "front"},
            {"path": str(files["back"]), "role": "back"},
        ], output, {},
    )
    assert output.is_file()
    assert result["task_type"] == "multiview_to_model"
    create_request = next(request for request in requests if request.method == "POST")
    body = json.loads(create_request.content)
    assert body["type"] == "multiview_to_model"
    assert body["files"][0]["file_token"] == "token-front"
    assert body["files"][1] == {}
    assert body["files"][2]["file_token"] == "token-back"
    assert body["files"][3] == {}


def test_agent_rejects_mask_without_base_image(client):
    mask = _upload_image(client, "mask.png", (255, 255, 255))
    response = client.post(
        "/api/agent/plan",
        json={
            "brief": "Trocar apenas a área branca.",
            "target": "image",
            "references": [{"asset_id": mask["id"], "role": "mask"}],
            "local_first": True,
            "use_llm": False,
            "planner_mode": "rules",
            "output_resolution": "preview",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "IMAGE_BASE_REFERENCE_MISSING"


def test_typed_dag_rejects_image_output_connected_to_text_input(client):
    graph = {
        "version": 2,
        "nodes": [
            {"id": "asset", "type": "input.asset", "position": {"x": 0, "y": 0}, "config": {"asset_id": "missing"}},
            {"id": "enhance", "type": "llm.enhance", "position": {"x": 300, "y": 0}, "config": {"provider": "local.ollama"}},
        ],
        "edges": [
            {"id": "bad", "source": "asset", "target": "enhance", "source_handle": "media", "target_handle": "prompt"}
        ],
        "metadata": {},
    }
    response = client.post("/api/workflows/validate", json=graph)
    assert response.status_code == 200
    payload = response.json()
    assert payload["valid"] is False
    assert any(item["code"] in {"SOURCE_PORT_INVALID", "PORT_TYPE_MISMATCH"} for item in payload["errors"])
