from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_endpoint() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json().get("status") == "ok"


def test_profile_endpoint_returns_shape() -> None:
    response = client.get("/profile")
    assert response.status_code == 200
    body = response.json()
    assert "profile" in body
    assert isinstance(body["profile"], dict)
