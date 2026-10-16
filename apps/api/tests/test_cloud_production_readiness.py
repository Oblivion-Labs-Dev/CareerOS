from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.rate_limit import RateLimitMiddleware
from app.services.storage_service import storage_service


def test_rate_limit_middleware_headers_and_throttling():
    test_app = FastAPI()
    test_app.add_middleware(RateLimitMiddleware, requests_per_minute=5)

    @test_app.get("/test-endpoint")
    def sample_endpoint():
        return {"ok": True}

    client = TestClient(test_app)

    # First request succeeds and returns RateLimit headers
    res1 = client.get("/test-endpoint")
    assert res1.status_code == 200
    assert "X-RateLimit-Limit" in res1.headers
    assert res1.headers["X-RateLimit-Limit"] == "5"

    # Send 4 more requests to exhaust the limit of 5
    for _ in range(4):
        res = client.get("/test-endpoint")
        assert res.status_code == 200

    # 6th request triggers 429
    res_blocked = client.get("/test-endpoint")
    assert res_blocked.status_code == 429
    assert res_blocked.json()["detail"] == "Too many requests. Please slow down."
    assert "Retry-After" in res_blocked.headers


def test_storage_service_local_save_and_retrieve(tmp_path):
    subfolder = "test_tailored_resumes"
    filename = "test_resume.pdf"
    content = b"%PDF-1.4 dummy pdf content for testing storage"

    saved_path = storage_service.save_file(subfolder, filename, content, "application/pdf")
    assert saved_path is not None

    local_path = storage_service.get_file_path(subfolder, filename)
    assert local_path is not None
    assert local_path.is_file()
    assert local_path.read_bytes() == content

    # Clean up test artifact
    try:
        local_path.unlink()
    except Exception:
        pass
