"""CAREEROS_LOCAL_LLM=off must mean no local model call, from any path.

The flag used to be checked only by some client factories. Other factories and
direct `LLMClient(...)` constructions ignored it, and a live run with the flag
off still asked Ollama for `mistral-small3.2:24b`. The switch now lives on the
client itself, so these tests go through every way a client gets built and
assert that none of them can reach the network while the flag is off.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.services.application_assistant import llm_client
from app.services.application_assistant.llm_client import (
    LLMClient,
    create_llm_client,
    create_mapping_client,
    create_vision_client,
)

LOCAL_SETTINGS = {
    "llm": {"baseUrl": "http://localhost:11434/v1", "model": "mistral-small3.2:24b", "provider": "ollama"},
    "fieldMapping": {"mappingModel": "qwen3:4b-instruct", "visionModel": "qwen2.5vl:7b"},
}


@pytest.fixture
def local_llm_off(monkeypatch):
    monkeypatch.setattr(llm_client, "LOCAL_LLM_ENABLED", False)


@pytest.fixture
def no_network(monkeypatch):
    """Any attempt to open an HTTP client fails the test."""

    def _refuse(*_args, **_kwargs):
        raise AssertionError("a model request was attempted with CAREEROS_LOCAL_LLM=off")

    monkeypatch.setattr(httpx, "AsyncClient", _refuse)


def _local_clients():
    from app.services.application_assistant.mistral_resume_match import build_mistral_match_client
    from app.services.repair.qwen_adapter import QwenCodingAgentAdapter

    return {
        # Built directly, never through a factory that checked the flag.
        "direct": LLMClient(base_url="http://localhost:11434/v1", model="mistral-small3.2:24b"),
        "direct-127": LLMClient(base_url="http://127.0.0.1:11434/v1", model="qwen3:8b"),
        "create_llm_client": create_llm_client(LOCAL_SETTINGS),
        "create_mapping_client": create_mapping_client(LOCAL_SETTINGS),
        "create_vision_client": create_vision_client(LOCAL_SETTINGS),
        "match-scoring": build_mistral_match_client(),
        "repair-adapter": QwenCodingAgentAdapter()._client,
    }


def test_no_local_client_is_enabled_when_the_flag_is_off(local_llm_off):
    for name, client in _local_clients().items():
        chain = client
        while chain is not None:
            if llm_client._is_local(chain.base_url):
                assert not chain.enabled, f"{name}: local client {chain.model} still enabled"
            chain = chain.fallback


def test_completion_and_chat_make_no_request_when_the_flag_is_off(local_llm_off, no_network):
    client = LLMClient(base_url="http://localhost:11434/v1", model="mistral-small3.2:24b")

    completion = asyncio.run(client.complete("Is this a match?"))
    chat = asyncio.run(client.chat([{"role": "user", "content": "hello"}]))
    ping = asyncio.run(client.test_connection())

    assert completion["success"] is False
    assert chat["success"] is False
    assert ping == {"success": False, "error": "LLM disabled", "provider": "ollama"}


def test_the_switch_only_governs_local_models(local_llm_off):
    remote = LLMClient(base_url="https://generativelanguage.googleapis.com/v1beta/openai", model="gemini-x")
    assert remote.enabled


def test_turning_the_flag_back_on_restores_local_clients(monkeypatch):
    monkeypatch.setattr(llm_client, "LOCAL_LLM_ENABLED", True)
    assert LLMClient(base_url="http://localhost:11434/v1", model="qwen3:8b").enabled


def test_startup_does_not_launch_ollama_when_the_flag_is_off(local_llm_off, monkeypatch):
    import subprocess

    from app import main

    launched: list[object] = []
    # Recorded rather than raised: the launcher swallows exceptions from Popen,
    # so a raising stub would let this test pass whether or not it was called.
    monkeypatch.setattr(subprocess, "Popen", lambda *args, **_kwargs: launched.append(args))
    monkeypatch.setattr("shutil.which", lambda _name: "ollama")  # as if Ollama were installed
    main._ensure_ollama_started_background()

    assert launched == [], "Ollama was launched with CAREEROS_LOCAL_LLM=off"
