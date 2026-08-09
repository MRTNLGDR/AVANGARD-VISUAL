from __future__ import annotations


def test_frontend_and_static_assets_are_served(client):
    index = client.get("/")
    assert index.status_code == 200
    assert "Avangard Visual" in index.text
    script = client.get("/app.js")
    assert script.status_code == 200
    assert "/api/governance/snapshot" in script.text
    assert "refetch" not in script.text or "refreshGovernance" in script.text
    styles = client.get("/styles.css")
    assert styles.status_code == 200
    assert ".workflow-node" in styles.text


def test_bootstrap_has_real_node_catalog(client):
    payload = client.get("/api/bootstrap").json()
    types = {item["type"] for item in payload["node_catalog"]}
    assert {"image.generate", "video.generate", "image.upscale", "video.upscale", "media.export"}.issubset(types)
    assert payload["app"]["profile"]["role"] == "super_admin"
