from __future__ import annotations


def test_api_rejects_dns_rebinding_host(client):
    response = client.get("/api/health", headers={"Host": "evil.example"})
    assert response.status_code == 403
    assert "Loopback Host" in response.json()["detail"]


def test_api_rejects_cross_site_browser_request(client):
    response = client.get(
        "/api/health",
        headers={"Sec-Fetch-Site": "cross-site", "Origin": "https://evil.example"},
    )
    assert response.status_code == 403


def test_api_rejects_wrong_local_token(client):
    response = client.get("/api/health", headers={"X-CineNode-Token": "wrong"})
    assert response.status_code == 401


def test_api_accepts_same_origin_and_valid_token(client):
    response = client.get(
        "/api/health",
        headers={
            "Origin": "http://testserver",
            "Sec-Fetch-Site": "same-origin",
            "X-CineNode-Token": "test-token",
        },
    )
    assert response.status_code == 200
