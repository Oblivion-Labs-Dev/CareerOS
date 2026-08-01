from app.services.application_assistant.llm_client import LLMClient


def test_ollama_payload_disables_thinking() -> None:
    client = LLMClient(base_url="http://localhost:11434/v1", model="qwen3:8b")
    payload: dict = {"model": "qwen3:8b", "messages": []}
    client._apply_ollama_thinking_off(payload)
    assert payload["reasoning_effort"] == "none"
    assert payload["think"] is False
    assert payload["chat_template_kwargs"] == {"enable_thinking": False}


def test_non_ollama_payload_unchanged() -> None:
    client = LLMClient(base_url="http://localhost:1234/v1", model="some-model")
    payload: dict = {"model": "some-model", "messages": []}
    client._apply_ollama_thinking_off(payload)
    assert "reasoning_effort" not in payload
    assert "think" not in payload
