"""Optional local LLM client for Application Assistant."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger("careeros.llm")


class LLMCallMetrics:
    """Process-wide, in-memory counters for which model actually answered each
    LLM call across the app (including both self-healing flows). Resets on
    backend restart — good enough for a first pass; move to persistent storage
    later if trend-over-time matters more than "since last restart"."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # per-model: {"success": int, "failure": int}
        self._by_model: dict[str, dict[str, int]] = {}
        self._by_provider: dict[str, dict[str, int]] = {}
        self.fallback_rescues = 0  # primary failed, fallback succeeded
        self.total_calls = 0

    def record(
        self,
        model: str,
        succeeded: bool,
        *,
        provider: str = "ollama",
        is_fallback: bool = False,
        task: str = "unspecified",
        latency_ms: float | None = None,
    ) -> None:
        with self._lock:
            self.total_calls += 1
            bucket = self._by_model.setdefault(model, {"success": 0, "failure": 0})
            bucket["success" if succeeded else "failure"] += 1

            p_bucket = self._by_provider.setdefault(provider, {"success": 0, "failure": 0})
            p_bucket["success" if succeeded else "failure"] += 1

            if is_fallback and succeeded:
                self.fallback_rescues += 1

        # Durable copy (this in-memory tracker resets on restart) — records
        # actual provider and model for later performance comparison.
        from app.services.model_usage_tracker import log_model_usage

        log_model_usage(
            provider=provider,
            model=model,
            task=task,
            success=succeeded,
            latency_ms=latency_ms,
        )

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "totalCalls": self.total_calls,
                "fallbackRescues": self.fallback_rescues,
                "byModel": {
                    model: dict(counts) for model, counts in self._by_model.items()
                },
                "byProvider": {
                    provider: dict(counts) for provider, counts in self._by_provider.items()
                },
            }

    def reset(self) -> None:
        with self._lock:
            self._by_model.clear()
            self._by_provider.clear()
            self.fallback_rescues = 0
            self.total_calls = 0


llm_call_metrics = LLMCallMetrics()


class LLMClient:
    """Provider-agnostic OpenAI-compatible LLM client."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:11434/v1",
        model: str = "qwen3:8b",
        api_key: str = "",
        timeout: int = 30,
        max_retries: int = 2,
        confidence_threshold: float = 0.7,
        fallback: "LLMClient | None" = None,
        provider: str = "ollama",
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.confidence_threshold = confidence_threshold
        # Secondary client tried when this one is unavailable or every retry fails.
        self.fallback = fallback
        self.provider = provider

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.model)

    async def test_connection(self) -> dict[str, Any]:
        """Test LLM connection."""
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                headers = self._headers()
                resp = await client.get(f"{self.base_url}/models", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("id", "") for m in data.get("data", [])]
                    return {"success": True, "models": models, "provider": self.provider, "model": self.model}
                return {"success": False, "error": f"HTTP {resp.status_code}", "provider": self.provider}
        except Exception as exc:
            return {"success": False, "error": str(exc), "provider": self.provider}

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system: str = "",
    ) -> dict[str, Any]:
        """Multi-turn chat completion, falling back to `self.fallback` if this client fails."""
        start_t = time.monotonic()
        result = await self._chat_once(messages, system=system) if self.enabled else {
            "success": False,
            "error": "LLM not configured",
        }
        latency_ms = (time.monotonic() - start_t) * 1000
        if self.enabled:
            llm_call_metrics.record(
                self.model,
                bool(result.get("success")),
                provider=self.provider,
                latency_ms=latency_ms,
            )
            logger.info(
                "LLM chat call: provider=%s model=%s success=%s latency=%.1fms",
                self.provider,
                self.model,
                bool(result.get("success")),
                latency_ms,
            )
        if not result.get("success") and self.fallback is not None and self.fallback.enabled:
            logger.warning(
                "LLM chat failed on provider=%s model=%s (%s). Falling back to provider=%s model=%s",
                self.provider,
                self.model,
                result.get("error"),
                self.fallback.provider,
                self.fallback.model,
            )
            fallback_result = await self.fallback.chat(messages, system=system)
            if fallback_result.get("success"):
                fallback_result["usedFallbackModel"] = fallback_result.get("usedFallbackModel") or self.fallback.model
                return fallback_result
        return result

    async def _chat_once(
        self,
        messages: list[dict[str, str]],
        *,
        system: str = "",
    ) -> dict[str, Any]:
        payload_messages: list[dict[str, str]] = []
        if system:
            payload_messages.append({"role": "system", "content": system})
        payload_messages.extend(messages)

        payload = {
            "model": self.model,
            "messages": payload_messages,
            "temperature": 0.7,
            "max_tokens": 2000,
            "stream": False,
        }
        self._apply_ollama_thinking_off(payload)

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=self._headers(),
                    )
                    if resp.status_code != 200:
                        if attempt < self.max_retries:
                            continue
                        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

                    data = resp.json()
                    choice = data.get("choices", [{}])[0]
                    content = choice.get("message", {}).get("content", "")
                    usage = data.get("usage", {})
                    return {
                        "success": True,
                        "data": content,
                        "usage": {
                            "promptTokens": usage.get("prompt_tokens", 0),
                            "completionTokens": usage.get("completion_tokens", 0),
                            "totalTokens": usage.get("total_tokens", 0),
                        },
                    }
            except httpx.TimeoutException:
                if attempt < self.max_retries:
                    continue
                return {"success": False, "error": "Request timed out"}
            except Exception as exc:
                if attempt < self.max_retries:
                    continue
                return {"success": False, "error": str(exc)}

        return {"success": False, "error": "Max retries exceeded"}

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Structured completion, falling back to `self.fallback` if this client fails."""
        start_t = time.monotonic()
        result = (
            await self._complete_once(prompt, system=system, response_schema=response_schema)
            if self.enabled
            else {"success": False, "error": "LLM not configured"}
        )
        latency_ms = (time.monotonic() - start_t) * 1000
        if self.enabled:
            llm_call_metrics.record(
                self.model,
                bool(result.get("success")),
                provider=self.provider,
                latency_ms=latency_ms,
            )
            logger.info(
                "LLM complete call: provider=%s model=%s success=%s latency=%.1fms",
                self.provider,
                self.model,
                bool(result.get("success")),
                latency_ms,
            )
        if not result.get("success") and self.fallback is not None and self.fallback.enabled:
            logger.warning(
                "LLM complete failed on provider=%s model=%s (%s). Falling back to provider=%s model=%s",
                self.provider,
                self.model,
                result.get("error"),
                self.fallback.provider,
                self.fallback.model,
            )
            fallback_result = await self.fallback.complete(
                prompt,
                system=system,
                response_schema=response_schema,
            )
            if fallback_result.get("success"):
                fallback_result["usedFallbackModel"] = fallback_result.get("usedFallbackModel") or self.fallback.model
                return fallback_result
        return result

    async def _complete_once(
        self,
        prompt: str,
        *,
        system: str = "",
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """
        Send a completion request with structured JSON output validation.
        Never used for Playwright control or sensitive answers.
        """
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        if response_schema:
            messages[0 if system else 0] = {
                "role": "system" if system else "user",
                "content": (system or prompt) + "\n\nRespond with valid JSON matching the requested schema.",
            }

        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1,
            "max_tokens": 2000,
        }
        if response_schema and self._is_ollama_compat():
            payload["format"] = "json"
        self._apply_ollama_thinking_off(payload)

        for attempt in range(self.max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    resp = await client.post(
                        f"{self.base_url}/chat/completions",
                        json=payload,
                        headers=self._headers(),
                    )
                    if resp.status_code != 200:
                        if attempt < self.max_retries:
                            continue
                        return {"success": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"}

                    data = resp.json()
                    message = data.get("choices", [{}])[0].get("message", {}) or {}
                    content = str(message.get("content") or "")

                    if response_schema:
                        parsed = self._parse_json_response(content)
                        if parsed is None:
                            return {"success": False, "error": "Invalid JSON response", "raw": content[:500]}
                        return {"success": True, "data": parsed, "confidence": parsed.get("confidence", 0.5)}

                    return {"success": True, "data": content}

            except httpx.TimeoutException:
                if attempt < self.max_retries:
                    continue
                return {"success": False, "error": "Request timed out"}
            except Exception as exc:
                if attempt < self.max_retries:
                    continue
                return {"success": False, "error": str(exc)}

        return {"success": False, "error": "Max retries exceeded"}

    async def normalize_field_label(self, label: str, known_keys: list[str]) -> dict[str, Any]:
        """Use LLM to map unfamiliar field label to known profile key."""
        schema = {
            "type": "object",
            "properties": {
                "matchedKey": {"type": "string"},
                "confidence": {"type": "number"},
                "reasoning": {"type": "string"},
            },
        }
        prompt = (
            f"Map this job application field label to the closest known profile key.\n"
            f"Label: \"{label}\"\n"
            f"Known keys: {json.dumps(known_keys)}\n"
            f"Respond with JSON: {{\"matchedKey\": \"...\", \"confidence\": 0.0-1.0, \"reasoning\": \"...\"}}"
        )
        result = await self.complete(prompt, response_schema=schema)
        if result.get("success") and result.get("confidence", 0) >= self.confidence_threshold:
            return result.get("data", {})
        return {"matchedKey": "", "confidence": 0, "reasoning": "Below confidence threshold"}

    async def explain_match(self, job_title: str, match_data: dict[str, Any]) -> str:
        """Generate human-readable match explanation."""
        prompt = (
            f"Explain this job match in 1-2 factual sentences.\n"
            f"Job: {job_title}\n"
            f"Score: {match_data.get('overallScore', 0)}\n"
            f"Strong matches: {match_data.get('strongMatches', [])}\n"
            f"Missing: {match_data.get('missingQualifications', [])}\n"
            f"Do not recommend applying or not applying. Just explain the match factually."
        )
        result = await self.complete(prompt)
        if result.get("success"):
            return str(result.get("data", ""))
        return match_data.get("explanation", "")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _is_ollama_compat(self) -> bool:
        lower = self.base_url.lower()
        return "11434" in lower or "ollama" in lower

    def _apply_ollama_thinking_off(self, payload: dict[str, Any]) -> None:
        """Qwen3 thinking models hang or burn tokens unless thinking is disabled."""
        if not self._is_ollama_compat():
            return
        # OpenAI-compatible Ollama endpoint ignores top-level `think`; use OpenAI fields.
        payload["reasoning_effort"] = "none"
        payload["think"] = False
        payload["chat_template_kwargs"] = {"enable_thinking": False}

    @staticmethod
    def _payload_after_thinking(content: str) -> str:
        """Keep only model output after the final closed thinking block."""
        text = content.strip()
        if not text:
            return text

        close_tags = (
            "<" + "/" + "think" + ">",
            "</" + "redacted_thinking" + ">",
        )
        lower = text.lower()
        last_end = -1
        for tag in close_tags:
            pos = lower.rfind(tag.lower())
            if pos >= 0:
                last_end = max(last_end, pos + len(tag))

        if last_end >= 0:
            return text[last_end:].strip()

        open_tags = ("<" + "think" + ">", "<" + "redacted_thinking" + ">")
        for open_tag in open_tags:
            pos = lower.find(open_tag.lower())
            if pos == 0:
                # Unclosed thinking prefix with no close tag — drop the reasoning block.
                return ""
        return text

    @staticmethod
    def _parse_json_object(text: str) -> dict[str, Any] | None:
        """Parse a JSON object from text, preferring the last valid object."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            cleaned = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:]).strip()

        if not cleaned:
            return None

        try:
            parsed = json.loads(cleaned)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass

        # Reasoning prose may precede the JSON — try each `{` from the end.
        brace_positions = [idx for idx, char in enumerate(cleaned) if char == "{"]
        for start in reversed(brace_positions):
            end = cleaned.rfind("}", start)
            if end <= start:
                continue
            try:
                parsed = json.loads(cleaned[start : end + 1])
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
        return None

    @staticmethod
    def _parse_json_response(content: str) -> dict[str, Any] | None:
        """Parse JSON from LLM response, handling markdown fences and Qwen thinking blocks."""
        text = LLMClient._payload_after_thinking(content)
        return LLMClient._parse_json_object(text)


class FreeTokenProvider(LLMClient):
    """FreeToken OpenAI-compatible local LLM provider.

    Connects to FreeToken server (typically http://127.0.0.1:1919/v1).
    Performs fast health checks before sending requests to prevent blocking
    when the FreeToken server is not running, and falls back to Mistral / Gemini.
    """

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:1919/v1",
        model: str = "Qwen3.6-35B-A3B",
        api_key: str = "",
        timeout: int = 60,
        max_retries: int = 0,
        confidence_threshold: float = 0.7,
        fallback: LLMClient | None = None,
        health_check_ttl: float = 5.0,
        health_check_timeout: float = 1.5,
    ):
        super().__init__(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries,
            confidence_threshold=confidence_threshold,
            fallback=fallback,
            provider="freetoken",
        )
        self.health_check_ttl = health_check_ttl
        self.health_check_timeout = health_check_timeout
        self._last_health_check_time: float = 0.0
        self._last_health_status: bool = False
        self._health_lock = asyncio.Lock()

    async def check_health(self, timeout: float | None = None) -> dict[str, Any]:
        """Probe FreeToken server health via GET /models."""
        t = timeout or self.health_check_timeout
        try:
            async with httpx.AsyncClient(timeout=t) as client:
                headers = self._headers()
                resp = await client.get(f"{self.base_url}/models", headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    models = [m.get("id", "") for m in data.get("data", [])] if isinstance(data, dict) else []
                    return {"healthy": True, "models": models}
                return {"healthy": False, "error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"healthy": False, "error": str(exc)}

    async def is_healthy(self, force: bool = False) -> bool:
        """Cached health check to avoid spamming the endpoint before every request."""
        now = time.monotonic()
        if not force and (now - self._last_health_check_time < self.health_check_ttl):
            return self._last_health_status

        async with self._health_lock:
            now = time.monotonic()
            if not force and (now - self._last_health_check_time < self.health_check_ttl):
                return self._last_health_status

            health = await self.check_health()
            self._last_health_status = bool(health.get("healthy"))
            self._last_health_check_time = now
            return self._last_health_status

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system: str = "",
    ) -> dict[str, Any]:
        if not self.enabled:
            return await self._fallback_chat(messages, system=system, reason="FreeToken not enabled")

        healthy = await self.is_healthy()
        if not healthy:
            logger.warning("FreeToken is unreachable at %s; bypassing to fallback", self.base_url)
            return await self._fallback_chat(messages, system=system, reason="FreeToken unreachable or unhealthy")

        return await super().chat(messages, system=system)

    async def complete(
        self,
        prompt: str,
        *,
        system: str = "",
        response_schema: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.enabled:
            return await self._fallback_complete(prompt, system=system, response_schema=response_schema, reason="FreeToken not enabled")

        healthy = await self.is_healthy()
        if not healthy:
            logger.warning("FreeToken is unreachable at %s; bypassing to fallback", self.base_url)
            return await self._fallback_complete(prompt, system=system, response_schema=response_schema, reason="FreeToken unreachable or unhealthy")

        return await super().complete(prompt, system=system, response_schema=response_schema)

    async def _fallback_chat(self, messages: list[dict[str, str]], *, system: str = "", reason: str = "") -> dict[str, Any]:
        if self.fallback is not None and self.fallback.enabled:
            res = await self.fallback.chat(messages, system=system)
            if res.get("success"):
                res["usedFallbackModel"] = res.get("usedFallbackModel") or self.fallback.model
            return res
        return {"success": False, "error": reason or "FreeToken unavailable and no fallback configured"}

    async def _fallback_complete(
        self,
        prompt: str,
        *,
        system: str = "",
        response_schema: dict[str, Any] | None = None,
        reason: str = "",
    ) -> dict[str, Any]:
        if self.fallback is not None and self.fallback.enabled:
            res = await self.fallback.complete(prompt, system=system, response_schema=response_schema)
            if res.get("success"):
                res["usedFallbackModel"] = res.get("usedFallbackModel") or self.fallback.model
            return res
        return {"success": False, "error": reason or "FreeToken unavailable and no fallback configured"}


def _is_freetoken_enabled(settings: dict[str, Any]) -> bool:
    from app.config import settings as app_settings

    ft_cfg = settings.get("freetoken") or {}
    if "enabled" in ft_cfg:
        return bool(ft_cfg["enabled"])
    llm_cfg = settings.get("llm") or {}
    if str(llm_cfg.get("provider") or "").lower() == "freetoken":
        return True

    if getattr(app_settings, "freetoken_enabled", False):
        return True
    return os.environ.get("FREETOKEN_ENABLED", "").lower() in ("true", "1", "yes")


def _resolve_llm_config(llm_config: dict[str, Any], default_model: str = "qwen3:8b") -> tuple[str, str, str]:
    """Resolve base_url, model, and api_key based on provider or explicit settings."""
    provider = str(llm_config.get("provider") or "").lower().strip()
    model = str(llm_config.get("model") or "").strip()
    api_key = str(llm_config.get("apiKey") or "").strip()
    base_url = str(llm_config.get("baseUrl") or "").strip()

    if provider in ("freetoken",) or (not provider and "1919" in base_url):
        base_url = base_url or os.environ.get("FREETOKEN_BASE_URL", "http://127.0.0.1:1919/v1")
        model = model or os.environ.get("FREETOKEN_MODEL", "Qwen3.6-35B-A3B")
        api_key = api_key or os.environ.get("FREETOKEN_API_KEY", "")
    elif provider in ("openai", "chatgpt") or (not provider and ("gpt" in model.lower() or "o1" in model.lower() or "o3" in model.lower())):
        base_url = base_url or "https://api.openai.com/v1"
        model = model or "gpt-4o-mini"
        api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    elif provider in ("gemini", "google") or (not provider and "gemini" in model.lower()):
        base_url = base_url or "https://generativelanguage.googleapis.com/v1beta/openai"
        model = model or "gemini-flash-latest"
        api_key = api_key or os.environ.get("GEMINI_API_KEY", "")
    elif provider in ("openrouter",) or (not provider and "openrouter" in base_url.lower()):
        base_url = base_url or os.environ.get("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1")
        model = model or "openai/gpt-4o-mini"
        api_key = api_key or os.environ.get("OPENROUTER_API_KEY", "")
    else:
        # Default Ollama / Local Mistral
        base_url = base_url or "http://localhost:11434/v1"
        model = model or default_model
        api_key = api_key

    return base_url, model, api_key


def _build_gemini_fallback(*, timeout: int, max_retries: int, confidence_threshold: float) -> LLMClient | None:
    """Gemini Flash client used as the automatic fallback when the primary model fails.

    Returns None when GEMINI_API_KEY isn't configured, so callers that never
    set that key see identical behavior to before (no fallback attempted).
    """
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key:
        return None
    return LLMClient(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        model="gemini-flash-latest",
        api_key=gemini_key,
        timeout=timeout,
        max_retries=max_retries,
        confidence_threshold=confidence_threshold,
        provider="gemini",
    )


def create_llm_client(settings: dict[str, Any]) -> LLMClient:
    """Create default LLM client from application assistant settings.

    Defaults to local Mistral via Ollama, automatically falling back to
    Gemini Flash when Mistral is unreachable or every retry fails.
    When FreeToken is enabled and healthy, FreeToken takes precedence as the
    primary local provider with automatic fallback to Mistral and Gemini.
    """
    llm_config = settings.get("llm", {})
    provider = str(llm_config.get("provider") or "").lower().strip()
    base_url, model, api_key = _resolve_llm_config(llm_config, default_model="mistral-small3.2:24b")
    timeout = llm_config.get("timeout", 60)
    max_retries = llm_config.get("maxRetries", 2)
    confidence_threshold = llm_config.get("confidenceThreshold", 0.7)
    gemini_fallback = None if "gemini" in model.lower() else _build_gemini_fallback(
        timeout=timeout, max_retries=max_retries, confidence_threshold=confidence_threshold
    )
    primary_max_retries = 0 if gemini_fallback is not None else max_retries

    mistral_provider_name = "ollama" if ("11434" in base_url or "ollama" in provider) else (provider or "ollama")
    mistral_client = LLMClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_retries=primary_max_retries,
        confidence_threshold=confidence_threshold,
        fallback=gemini_fallback,
        provider=mistral_provider_name,
    )

    if _is_freetoken_enabled(settings):
        from app.config import settings as app_settings

        ft_cfg = settings.get("freetoken") or {}
        ft_base_url = (
            ft_cfg.get("baseUrl")
            or getattr(app_settings, "freetoken_base_url", None)
            or os.environ.get("FREETOKEN_BASE_URL", "http://127.0.0.1:1919/v1")
        )
        ft_model = (
            ft_cfg.get("model")
            or getattr(app_settings, "freetoken_model", None)
            or os.environ.get("FREETOKEN_MODEL", "Qwen3.6-35B-A3B")
        )
        ft_timeout = int(
            ft_cfg.get("timeout")
            or getattr(app_settings, "freetoken_timeout", 60)
            or os.environ.get("FREETOKEN_TIMEOUT", 60)
        )
        ft_api_key = (
            ft_cfg.get("apiKey")
            or getattr(app_settings, "freetoken_api_key", "")
            or os.environ.get("FREETOKEN_API_KEY", "")
        )
        return FreeTokenProvider(
            base_url=ft_base_url,
            model=ft_model,
            api_key=ft_api_key,
            timeout=ft_timeout,
            max_retries=0,
            confidence_threshold=confidence_threshold,
            fallback=mistral_client,
        )

    return mistral_client


def create_mapping_client(settings: dict[str, Any]) -> LLMClient:
    """Text mapping model (field interpretation planner). Mistral primary, Gemini fallback."""
    llm_config = settings.get("llm", {})
    field_mapping = settings.get("fieldMapping") or {}
    model_override = field_mapping.get("mappingModel") or llm_config.get("mappingModel")

    cfg = dict(llm_config)
    if model_override:
        cfg["model"] = model_override

    base_url, model, api_key = _resolve_llm_config(cfg, default_model="mistral-small3.2:24b")
    timeout = llm_config.get("timeout", 90)
    max_retries = llm_config.get("maxRetries", 2)
    confidence_threshold = llm_config.get("confidenceThreshold", 0.7)
    gemini_fallback = None if "gemini" in model.lower() else _build_gemini_fallback(
        timeout=timeout, max_retries=max_retries, confidence_threshold=confidence_threshold
    )
    primary_max_retries = 0 if gemini_fallback is not None else max_retries

    provider = str(cfg.get("provider") or "").lower().strip()
    mistral_provider_name = "ollama" if ("11434" in base_url or "ollama" in provider) else (provider or "ollama")
    mistral_client = LLMClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_retries=primary_max_retries,
        confidence_threshold=confidence_threshold,
        fallback=gemini_fallback,
        provider=mistral_provider_name,
    )

    if _is_freetoken_enabled(settings):
        from app.config import settings as app_settings

        ft_cfg = settings.get("freetoken") or {}
        ft_base_url = (
            ft_cfg.get("baseUrl")
            or getattr(app_settings, "freetoken_base_url", None)
            or os.environ.get("FREETOKEN_BASE_URL", "http://127.0.0.1:1919/v1")
        )
        ft_model = (
            ft_cfg.get("model")
            or getattr(app_settings, "freetoken_model", None)
            or os.environ.get("FREETOKEN_MODEL", "Qwen3.6-35B-A3B")
        )
        ft_timeout = int(
            ft_cfg.get("timeout")
            or getattr(app_settings, "freetoken_timeout", 90)
            or os.environ.get("FREETOKEN_TIMEOUT", 90)
        )
        ft_api_key = (
            ft_cfg.get("apiKey")
            or getattr(app_settings, "freetoken_api_key", "")
            or os.environ.get("FREETOKEN_API_KEY", "")
        )
        return FreeTokenProvider(
            base_url=ft_base_url,
            model=ft_model,
            api_key=ft_api_key,
            timeout=ft_timeout,
            max_retries=0,
            confidence_threshold=confidence_threshold,
            fallback=mistral_client,
        )

    return mistral_client


def create_vision_client(settings: dict[str, Any]) -> LLMClient:
    """Optional vision model for ambiguous fields."""
    llm_config = settings.get("llm", {})
    field_mapping = settings.get("fieldMapping") or {}
    model = field_mapping.get("visionModel") or llm_config.get("visionModel") or ""
    if not model or not field_mapping.get("visionEnabled", False):
        return LLMClient(base_url="", model="")
    
    cfg = dict(llm_config)
    cfg["model"] = model
    base_url, model, api_key = _resolve_llm_config(cfg, default_model="gpt-4o")
    return LLMClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout=llm_config.get("timeout", 120),
        max_retries=llm_config.get("maxRetries", 1),
        confidence_threshold=llm_config.get("confidenceThreshold", 0.7),
    )


async def call_llm(system: str, prompt: str, settings: dict[str, Any] | None = None) -> str:
    """Call LLM with system prompt and user prompt, supporting local Ollama Mistral and Gemini Flash."""
    client = create_llm_client(settings or {})
    if client.enabled:
        res = await client.chat([{"role": "user", "content": prompt}], system=system)
        if res.get("success"):
            data_val = res.get("data") or res.get("content") or ""
            if data_val:
                return str(data_val)
    # Gemini Flash fallback via OpenRouter / LLM service
    try:
        from app.services.llm import call_openrouter_json
        openrouter_res = await call_openrouter_json(prompt, system_instruction=system)
        if openrouter_res:
            return json.dumps(openrouter_res)
    except Exception:
        pass
    return ""


