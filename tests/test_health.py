from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json().get("status") == "ok"


def test_root_returns_html_dashboard() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers.get("content-type", "")
    assert "CareerOS API" in response.text
    assert "chart-tps" in response.text
    assert "Request flow" in response.text
    assert "error-fix-history" in response.text


def test_metrics_endpoint_returns_runtime_stats() -> None:
    client.get("/health")
    response = client.get("/metrics")
    assert response.status_code == 200
    body = response.json()
    assert "totalRequests" in body
    assert "latencyMs" in body
    assert "tps" in body
    assert "errorFix" in body
    assert body["totalRequests"] >= 1
    assert "avg" in body["latencyMs"]


def test_profile_endpoint_returns_shape() -> None:
    response = client.get("/profile")
    assert response.status_code == 200
    body = response.json()
    assert "profile" in body
    assert isinstance(body["profile"], dict)
