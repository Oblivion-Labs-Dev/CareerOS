"""Local models were removed: no settings can bring one back.

Old saved settings may still name a local endpoint (Ollama on 11434, or
localhost). Every client factory must turn those into Gemini (when a key is
configured) or a disabled client, never a client that talks to this machine.
"""

from __future__ import annotations

import pytest

from app.services.application_assistant import llm_client
from app.services.application_assistant.llm_client import (
    create_llm_client,
    create_mapping_client,
    create_vision_client,
)

LOCAL_SETTINGS = [
    {"llm": {"baseUrl": "http://localhost:11434/v1", "model": "qwen2.5:7b"}},
    {"llm": {"baseUrl": "http://127.0.0.1:11434/v1", "model": "mistral-small3.2:24b"}},
    {"llm": {"provider": "ollama", "model": "qwen2.5:3b"}},
    {"llm": {"model": "qwen2.5:3b"}},
    {},
]


def _is_local_client(client) -> bool:
    return llm_client._is_local(client.base_url)


@pytest.fixture()
def no_gemini(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)


@pytest.mark.parametrize("settings", LOCAL_SETTINGS)
def test_local_settings_without_gemini_give_a_disabled_client(no_gemini, settings):
    for factory in (create_llm_client, create_mapping_client):
        client = factory(settings)
        assert not client.enabled
        assert not _is_local_client(client)


@pytest.mark.parametrize("settings", LOCAL_SETTINGS)
def test_local_settings_with_gemini_use_gemini(monkeypatch, settings):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key-not-real")
    monkeypatch.setattr("app.services.gemini.config.applications_enabled", lambda: True)
    for factory in (create_llm_client, create_mapping_client):
        client = factory(settings)
        assert client.enabled
        assert "generativelanguage.googleapis.com" in client.base_url
        assert not _is_local_client(client)


def test_vision_client_pointed_at_a_local_endpoint_is_never_enabled(no_gemini):
    client = create_vision_client(
        {
            "llm": {"baseUrl": "http://localhost:11434/v1", "visionModel": "llava"},
            "fieldMapping": {"visionEnabled": True},
        }
    )
    assert not client.enabled


def test_the_api_does_not_start_a_local_model_server():
    import inspect

    import app.main as main

    source = inspect.getsource(main).lower()
    assert "ollama" not in source
    assert "11434" not in source
