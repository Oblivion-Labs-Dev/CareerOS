"""The one place Career OS talks to DeepSeek. Server-side only."""
from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, TypeVar

import httpx
from pydantic import BaseModel, ValidationError

logger = logging.getLogger("careeros.deepseek")
T = TypeVar("T", bound=BaseModel)

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


class DeepSeekError(RuntimeError):
    """A failed call. `code` is one of: disabled, auth, timeout, http, malformed."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _api_key() -> str:
    key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    if key:
        return key
    from dotenv import dotenv_values
    api_root = Path(__file__).resolve().parents[3]
    for env_file in (api_root / ".env", api_root.parents[1] / ".env"):
        if env_file.is_file():
            key = str(dotenv_values(env_file).get("DEEPSEEK_API_KEY") or "").strip()
            if key:
                return key
    return ""


def _extract_json(content: str) -> Any:
    text = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.S)
    if fenced:
        text = fenced.group(1)
    return json.loads(text)


class DeepSeekClient:
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None, model: str | None = None,
                 timeout: float = 60.0, transport: httpx.BaseTransport | None = None):
        self._api_key = api_key if api_key is not None else _api_key()
        self.base_url = (base_url or os.environ.get("DEEPSEEK_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self.model = model or os.environ.get("DEEPSEEK_MODEL") or DEFAULT_MODEL
        self.timeout = timeout
        self._transport = transport

    @property
    def configured(self) -> bool:
        return bool(self._api_key)

    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self._api_key:
            raise DeepSeekError("disabled", "DEEPSEEK_API_KEY is not set on the API server.")
        try:
            with httpx.Client(timeout=self.timeout, transport=self._transport) as client:
                response = client.post(f"{self.base_url}/chat/completions", json=payload,
                                       headers={"Authorization": f"Bearer {self._api_key}"})
        except httpx.TimeoutException as exc:
            raise DeepSeekError("timeout", f"DeepSeek did not answer within {self.timeout:.0f}s.") from exc
        except httpx.HTTPError as exc:
            raise DeepSeekError("http", f"Could not reach DeepSeek: {type(exc).__name__}.") from exc
        if response.status_code in (401, 403):
            raise DeepSeekError("auth", "DeepSeek rejected the API key.")
        if response.status_code >= 400:
            raise DeepSeekError("http", f"DeepSeek returned HTTP {response.status_code}.")
        try:
            return response.json()
        except ValueError as exc:
            raise DeepSeekError("malformed", "DeepSeek returned a non-JSON HTTP body.") from exc

    def complete_json(self, *, task: str, system: str, user: dict[str, Any] | str, schema: type[T],
                      max_tokens: int = 2000, temperature: float = 0.2) -> tuple[T, dict[str, Any]]:
        """Ask for one JSON object and validate it against `schema`.

        One retry is made when the content is not valid JSON or does not match
        the schema; the second failure raises DeepSeekError("malformed").
        """
        messages = [
            {"role": "system", "content": system + "\nRespond with a single JSON object only."},
            {"role": "user", "content": user if isinstance(user, str) else json.dumps(user, ensure_ascii=False)},
        ]
        last_problem = ""
        for attempt in range(2):
            started = time.perf_counter()
            body = self._post({"model": self.model, "messages": messages, "temperature": temperature,
                               "max_tokens": max_tokens, "response_format": {"type": "json_object"}})
            latency = round((time.perf_counter() - started) * 1000)
            usage = body.get("usage") or {}
            logger.info("deepseek task=%s model=%s attempt=%d latency_ms=%d tokens=%s",
                        task, self.model, attempt + 1, latency, usage.get("total_tokens"))
            try:
                content = body["choices"][0]["message"]["content"] or ""
                parsed = schema.model_validate(_extract_json(content))
                return parsed, {"task": task, "model": self.model, "latency_ms": latency, "attempts": attempt + 1,
                                "tokens": usage.get("total_tokens"), "prompt_tokens": usage.get("prompt_tokens"),
                                "completion_tokens": usage.get("completion_tokens"), "temperature": temperature}
            except (KeyError, IndexError, TypeError, ValueError, ValidationError) as exc:
                last_problem = f"{type(exc).__name__}: {str(exc)[:300]}"
                messages = messages[:2] + [{"role": "user", "content":
                    "Your last reply was not valid for the required JSON shape. Problem: " + last_problem +
                    ". Reply again with only the corrected JSON object."}]
        raise DeepSeekError("malformed", f"DeepSeek returned invalid JSON for {task}: {last_problem}")
