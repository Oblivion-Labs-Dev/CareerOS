import asyncio
from typing import Any

import pytest
from fastapi import HTTPException

from app.routers import api
from app.services import llm


def generation_kwargs() -> dict[str, Any]:
    return {
        "target_company": "Example Co",
        "target_role": "Staff Platform Engineer",
        "job_description": "Build reliable distributed systems.",
        "experience_level": "Staff",
        "tone": "professional",
        "max_pages": 1,
        "target_ats": 85,
    }


def payload(accomplishment_ids: list[str]) -> api.ResumeGeneratePayload:
    return api.ResumeGeneratePayload(
        accomplishmentIds=accomplishment_ids,
        targetCompany="Example Co",
        targetRole="Staff Platform Engineer",
        jobDescription="Build reliable distributed systems.",
    )


def test_provider_failure_returns_no_fabricated_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    async def unavailable(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(llm, "call_openrouter_json", unavailable)
    result = asyncio.run(
        llm.generate_resume_bullets_for_job(
            accomplishments=[{"id": "acc-1", "company": "Northstar", "project": "Routing"}],
            **generation_kwargs(),
        )
    )

    assert result is None


def test_generation_keeps_source_identity_without_calling_provider(monkeypatch):
    async def forbidden(*args, **kwargs):
        pytest.fail("Resume generation must stay local")
    monkeypatch.setattr(llm, "call_openrouter_json", forbidden)
    source = {"id": "acc-1", "company": "Northstar", "project": "Routing", "role": "Staff engineer",
              "evidenceTier": "professional", "currentBullet": "Built reliable distributed systems using Kafka for durable message delivery."}
    result = asyncio.run(llm.generate_resume_bullets_for_job(accomplishments=[source], **generation_kwargs()))
    assert result is not None
    assert result["atsMatchScore"] is None
    assert result["provenance"] == "selected-records"
    assert result["resumeBullets"][0]["optimizedBullet"] == source["currentBullet"]
    assert result["resumeBullets"][0]["company"] == "Northstar"


def test_resume_route_rejects_empty_or_missing_selections(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "get_kv", lambda *args: {})
    monkeypatch.setattr(api, "list_entities", lambda _db, _kind: [{"id": "acc-1"}])

    with pytest.raises(HTTPException) as empty_error:
        asyncio.run(api.generate_resume_route(payload([]), db=object()))
    assert empty_error.value.status_code == 503  # Empty selection searches all records; none has a usable bullet.

    with pytest.raises(HTTPException) as missing_error:
        asyncio.run(api.generate_resume_route(payload(["missing"]), db=object()))
    assert missing_error.value.status_code == 422


def test_resume_route_surfaces_provider_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api, "get_kv", lambda *args: {})
    monkeypatch.setattr(api, "list_entities", lambda _db, _kind: [{"id": "acc-1"}])

    async def unavailable(**_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(api, "generate_resume_bullets_for_job", unavailable)

    with pytest.raises(HTTPException) as unavailable_error:
        asyncio.run(api.generate_resume_route(payload(["acc-1"]), db=object()))
    assert unavailable_error.value.status_code == 503
    assert "No synthetic fallback content" in str(unavailable_error.value.detail)
