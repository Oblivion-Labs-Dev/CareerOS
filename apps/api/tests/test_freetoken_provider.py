"""Unit tests for FreeToken local LLM provider integration."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from app.services.application_assistant.llm_client import (
    FreeTokenProvider,
    LLMClient,
    create_llm_client,
    llm_call_metrics,
)


@pytest.fixture(autouse=True)
def reset_metrics():
    llm_call_metrics.reset()
    yield
    llm_call_metrics.reset()


def test_freetoken_provider_init():
    provider = FreeTokenProvider(
        base_url="http://127.0.0.1:1919/v1",
        model="Qwen3.6-35B-A3B",
        timeout=45,
    )
    assert provider.provider == "freetoken"
    assert provider.base_url == "http://127.0.0.1:1919/v1"
    assert provider.model == "Qwen3.6-35B-A3B"
    assert provider.timeout == 45
    assert provider.enabled is True


@pytest.mark.anyio
async def test_freetoken_check_health_success():
    provider = FreeTokenProvider(base_url="http://127.0.0.1:1919/v1", model="Qwen3.6-35B-A3B")

    from unittest.mock import MagicMock

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"id": "Qwen3.6-35B-A3B"}]}

    with patch("httpx.AsyncClient.get", return_value=mock_resp):
        health = await provider.check_health()
        assert health["healthy"] is True
        assert "Qwen3.6-35B-A3B" in health["models"]

        is_healthy = await provider.is_healthy()
        assert is_healthy is True


@pytest.mark.anyio
async def test_freetoken_check_health_unreachable():
    provider = FreeTokenProvider(base_url="http://127.0.0.1:1919/v1", model="Qwen3.6-35B-A3B")

    with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
        health = await provider.check_health()
        assert health["healthy"] is False
        assert "Connection refused" in health["error"]

        is_healthy = await provider.is_healthy()
        assert is_healthy is False


@pytest.mark.anyio
async def test_freetoken_unhealthy_fast_fallback_to_mistral():
    mistral_fallback = LLMClient(
        base_url="http://localhost:11434/v1",
        model="mistral-small3.2:24b",
        provider="ollama",
    )
    provider = FreeTokenProvider(
        base_url="http://127.0.0.1:1919/v1",
        model="Qwen3.6-35B-A3B",
        fallback=mistral_fallback,
    )

    # Mock FreeToken health check as failing (e.g. server offline)
    with patch.object(provider, "is_healthy", return_value=False):
        with patch.object(
            mistral_fallback,
            "complete",
            return_value={"success": True, "data": {"answer": "Option A"}, "confidence": 0.95},
        ) as mock_mistral_complete:
            result = await provider.complete("Test prompt", response_schema={"type": "object"})
            assert result["success"] is True
            assert result["data"]["answer"] == "Option A"
            assert result["usedFallbackModel"] == "mistral-small3.2:24b"
            mock_mistral_complete.assert_called_once()


@pytest.mark.anyio
async def test_freetoken_healthy_executes_request():
    mistral_fallback = LLMClient(
        base_url="http://localhost:11434/v1",
        model="mistral-small3.2:24b",
        provider="ollama",
    )
    provider = FreeTokenProvider(
        base_url="http://127.0.0.1:1919/v1",
        model="Qwen3.6-35B-A3B",
        fallback=mistral_fallback,
    )

    # FreeToken is healthy and returns response
    with patch.object(provider, "is_healthy", return_value=True):
        with patch.object(
            provider,
            "_complete_once",
            return_value={"success": True, "data": {"matchedKey": "firstName"}, "confidence": 0.98},
        ):
            result = await provider.complete("Test prompt", response_schema={"type": "object"})
            assert result["success"] is True
            assert result["data"]["matchedKey"] == "firstName"
            assert "usedFallbackModel" not in result

            # Verify metrics recorded with provider "freetoken"
            metrics = llm_call_metrics.to_dict()
            assert metrics["totalCalls"] == 1
            assert "freetoken" in metrics["byProvider"]
            assert metrics["byProvider"]["freetoken"]["success"] == 1


@pytest.mark.anyio
async def test_freetoken_cascades_to_mistral_then_gemini():
    gemini_client = LLMClient(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-flash-latest",
        provider="gemini",
    )
    mistral_client = LLMClient(
        base_url="http://localhost:11434/v1",
        model="mistral-small3.2:24b",
        provider="ollama",
        fallback=gemini_client,
    )
    provider = FreeTokenProvider(
        base_url="http://127.0.0.1:1919/v1",
        model="Qwen3.6-35B-A3B",
        fallback=mistral_client,
    )

    # FreeToken is healthy but request fails -> Mistral fails -> Gemini succeeds
    with patch.object(provider, "is_healthy", return_value=True):
        with patch.object(provider, "_complete_once", return_value={"success": False, "error": "CUDA OOM"}):
            with patch.object(mistral_client, "_complete_once", return_value={"success": False, "error": "Ollama timeout"}):
                with patch.object(
                    gemini_client,
                    "_complete_once",
                    return_value={"success": True, "data": {"answer": "Recovered by Gemini"}},
                ):
                    result = await provider.complete("Test prompt")
                    assert result["success"] is True
                    assert result["data"]["answer"] == "Recovered by Gemini"
                    assert result["usedFallbackModel"] == "gemini-flash-latest"


def test_create_llm_client_default_preserves_mistral():
    settings = {
        "llm": {
            "enabled": True,
            "baseUrl": "http://localhost:11434/v1",
            "model": "mistral-small3.2:24b",
            "provider": "ollama",
        }
    }
    with patch("app.services.application_assistant.llm_client._is_freetoken_enabled", return_value=False):
        client = create_llm_client(settings)
        assert not isinstance(client, FreeTokenProvider)
        assert client.model == "mistral-small3.2:24b"
        assert client.provider == "ollama"


def test_create_llm_client_with_freetoken_enabled():
    settings = {
        "llm": {
            "enabled": True,
            "baseUrl": "http://localhost:11434/v1",
            "model": "mistral-small3.2:24b",
            "provider": "ollama",
        },
        "freetoken": {
            "enabled": True,
            "baseUrl": "http://127.0.0.1:1919/v1",
            "model": "Qwen3.6-35B-A3B",
            "timeout": 40,
        },
    }
    client = create_llm_client(settings)
    assert isinstance(client, FreeTokenProvider)
    assert client.provider == "freetoken"
    assert client.model == "Qwen3.6-35B-A3B"
    assert client.timeout == 40
    # Fallback should be Mistral
    assert client.fallback is not None
    assert client.fallback.model == "mistral-small3.2:24b"
    assert client.fallback.provider == "ollama"


def test_thinking_tag_removal_and_json_parsing():
    raw_response = (
        "<think>\n"
        "Let me analyze the field question: Are you authorized to work in the US?\n"
        "Candidate has US citizenship.\n"
        "</think>\n"
        "```json\n"
        "{\n"
        '  "classification": "WORK_AUTHORIZED",\n'
        '  "answer": "Yes",\n'
        '  "confidence": 0.99\n'
        "}\n"
        "```"
    )
    parsed = LLMClient._parse_json_response(raw_response)
    assert parsed is not None
    assert parsed["classification"] == "WORK_AUTHORIZED"
    assert parsed["answer"] == "Yes"
    assert parsed["confidence"] == 0.99
