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

# Ollama serves every model at OLLAMA_CONTEXT_LENGTH (default 4096) regardless
# of the context length on the model card. Keep this in step with the env var
# the dev stack sets, so prompt budgeting reflects what the server will really
# accept rather than what the model could theoretically handle.
DEFAULT_CONTEXT_WINDOW = int(os.environ.get("OLLAMA_CONTEXT_LENGTH", "16384"))


def estimate_tokens(text: str) -> int:
    """Cheap token estimate (~4 chars/token) for prompt budgeting.

    Deliberately not a real tokenizer: this is used to decide how much of a
    job description to keep, where being approximately right and free beats
    being exact and pulling in a tokenizer dependency per model.
    """
    return max(1, len(text or "") // 4)


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
        # Every hand-off from a primary model to its fallback, with the reason.
        # Kept bounded so a long-running process cannot grow this unboundedly.
        self.fallback_events: list[dict[str, Any]] = []
        self.retries = 0

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

    def record_fallback(self, primary_model: str, fallback_model: str, reason: str) -> None:
        with self._lock:
            self.fallback_events.append({
                "from": primary_model,
                "to": fallback_model,
                "reason": reason,
                "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            })
            del self.fallback_events[:-50]

    def record_retry(self, model: str) -> None:
        with self._lock:
            self.retries += 1

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
                "retries": self.retries,
                "fallbackEvents": list(self.fallback_events[-20:]),
            }

    def reset(self) -> None:
        with self._lock:
            self._by_model.clear()
            self._by_provider.clear()
            self.fallback_rescues = 0
            self.total_calls = 0
            self.retries = 0
            self.fallback_events.clear()


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
        context_window: int = DEFAULT_CONTEXT_WINDOW,
        max_output_tokens: int = 2000,
        temperature: float | None = None,
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
        # How many tokens this model is actually being served with. Ollama
        # serves OLLAMA_CONTEXT_LENGTH, not the model card maximum, and a
        # prompt that overflows it is silently truncated — callers that build
        # large prompts (resume tailoring) size themselves against this.
        self.context_window = context_window
        self.max_output_tokens = max_output_tokens
        # Sampling temperature. None keeps each call path's own default; a
        # caller that needs a reproducible answer sets it explicitly. Match
        # scoring does: a score used as a gate has to be the same number twice
        # for the same input, and at the default the identical resume came back
        # at 77.9% and 86.5% minutes apart, which made "did tailoring improve
        # this resume" unanswerable.
        self.temperature = temperature

    @property
    def enabled(self) -> bool:
        # CAREEROS_LOCAL_LLM=off is enforced here, on every client, rather than
        # only in the factories: several paths build a local client directly or
        # through a factory that never consulted the flag, and one of them loaded
        # a 24B model with the flag off. Every caller already treats a disabled
        # client as "use the deterministic path", so this is the one place that
        # makes the flag mean "no local model calls at all".
        if not LOCAL_LLM_ENABLED and _is_local(self.base_url):
            return False
        return bool(self.base_url and self.model)

    async def test_connection(self) -> dict[str, Any]:
        """Test LLM connection."""
        if not self.enabled:
            return {"success": False, "error": "LLM disabled", "provider": self.provider}
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
            "temperature": 0.7 if self.temperature is None else self.temperature,
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
        task: str = "unspecified",
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
                task=task,
            )
            self._log_call("complete", result, latency_ms, prompt=prompt, system=system, task=task)
        if not result.get("success") and self.fallback is not None and self.fallback.enabled:
            logger.warning(
                "LLM fallback: task=%s provider=%s model=%s failed (%s) -> provider=%s model=%s",
                task,
                self.provider,
                self.model,
                result.get("error"),
                self.fallback.provider,
                self.fallback.model,
            )
            llm_call_metrics.record_fallback(self.model, self.fallback.model, str(result.get("error"))[:200])
            fallback_result = await self.fallback.complete(
                prompt,
                system=system,
                response_schema=response_schema,
                task=task,
            )
            if fallback_result.get("success"):
                fallback_result["usedFallbackModel"] = fallback_result.get("usedFallbackModel") or self.fallback.model
                # Count the rescue here. record() is called by the *fallback*
                # client for its own call and has no way to know it was acting
                # as a fallback, which is why this counter read 0 through a real
                # Qwen -> Mistral rescue while fallbackEvents recorded it.
                llm_call_metrics.fallback_rescues += 1
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

        # Leave room for the answer inside the context the server actually
        # serves. Asking for a flat 2000 on top of a large prompt is how a
        # request silently overflows and comes back truncated.
        prompt_tokens = estimate_tokens("".join(m["content"] for m in messages))
        headroom = self.context_window - prompt_tokens - 128
        max_out = max(256, min(self.max_output_tokens, headroom))
        if headroom < 256:
            logger.warning(
                "LLM complete: prompt ~%d tokens leaves only %d of a %d-token context "
                "for the answer; the caller should shrink the prompt",
                prompt_tokens, headroom, self.context_window,
            )
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.1 if self.temperature is None else self.temperature,
            "max_tokens": max_out,
        }
        if response_schema and self._is_ollama_compat():
            # `response_format`, not `format`. This client talks to Ollama's
            # OpenAI-compatible endpoint (/v1/chat/completions), which accepts
            # the OpenAI field and silently ignores Ollama's native `format`.
            # So the previous `format: "json"` was never doing anything at all,
            # and neither was passing the schema under that key.
            #
            # Measured A/B on mistral:7b-instruct, same prompt, same seed:
            #   format: <schema>          -> prose, does not parse
            #   response_format: schema   -> valid JSON
            #
            # This mattered well beyond the benchmark. A response that failed to
            # parse was recorded as "unscored", and an unscored job never
            # entered the Autopilot queue, so real postings were being dropped
            # because of a request field the server was throwing away.
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": "structured_response",
                    "strict": True,
                    "schema": response_schema,
                },
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
                    message = data.get("choices", [{}])[0].get("message", {}) or {}
                    content = str(message.get("content") or "")
                    raw_usage = data.get("usage") or {}
                    usage = {
                        "promptTokens": raw_usage.get("prompt_tokens", 0),
                        "completionTokens": raw_usage.get("completion_tokens", 0),
                        "totalTokens": raw_usage.get("total_tokens", 0),
                    }
                    finish_reason = data.get("choices", [{}])[0].get("finish_reason", "")
                    if finish_reason == "length":
                        logger.warning(
                            "LLM complete: model=%s hit the output cap (%d tokens) — "
                            "the answer is truncated",
                            self.model, max_out,
                        )

                    if response_schema:
                        parsed = self._parse_json_response(content)
                        if parsed is None:
                            return {
                                "success": False,
                                "error": "Invalid JSON response",
                                "raw": content[:500],
                                "usage": usage,
                                "attempts": attempt + 1,
                                "finishReason": finish_reason,
                            }
                        return {
                            "success": True,
                            "data": parsed,
                            "confidence": parsed.get("confidence", 0.5),
                            "usage": usage,
                            "attempts": attempt + 1,
                            "finishReason": finish_reason,
                        }

                    return {
                        "success": True,
                        "data": content,
                        "usage": usage,
                        "attempts": attempt + 1,
                        "finishReason": finish_reason,
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

    def _log_call(
        self,
        kind: str,
        result: dict[str, Any],
        latency_ms: float,
        *,
        prompt: str = "",
        system: str = "",
        task: str = "unspecified",
    ) -> None:
        """One structured line per LLM call: model, tokens, latency, context use.

        Token counts come from the provider's own `usage` block when it sends
        one and fall back to an estimate otherwise, so the context-usage figure
        is always populated — an overflowing prompt is silently truncated by
        Ollama, and this line is what makes that visible.
        """
        usage = result.get("usage") or {}
        prompt_tokens = usage.get("promptTokens") or estimate_tokens(system + prompt)
        completion_tokens = usage.get("completionTokens") or estimate_tokens(str(result.get("raw") or ""))
        total = prompt_tokens + completion_tokens
        pct = (total / self.context_window * 100) if self.context_window else 0.0
        logger.info(
            "LLM %s: task=%s provider=%s model=%s success=%s latency=%.0fms "
            "tokens_in=%d tokens_out=%d ctx=%d/%d (%.0f%%) retries=%d%s",
            kind,
            task,
            self.provider,
            self.model,
            bool(result.get("success")),
            latency_ms,
            prompt_tokens,
            completion_tokens,
            total,
            self.context_window,
            pct,
            int(result.get("attempts", 1)) - 1,
            "" if result.get("success") else f" error={str(result.get('error'))[:120]}",
        )
        if pct >= 90:
            logger.warning(
                "LLM %s: task=%s model=%s used %.0f%% of its %d-token context — "
                "the prompt may have been truncated server-side",
                kind, task, self.model, pct, self.context_window,
            )

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


def _resolve_llm_config(llm_config: dict[str, Any], default_model: str = "qwen3:8b") -> tuple[str, str, str]:
    """Resolve base_url, model, and api_key based on provider or explicit settings."""
    provider = str(llm_config.get("provider") or "").lower().strip()
    model = str(llm_config.get("model") or "").strip()
    api_key = str(llm_config.get("apiKey") or "").strip()
    base_url = str(llm_config.get("baseUrl") or "").strip()

    if provider in ("openai", "chatgpt") or (not provider and ("gpt" in model.lower() or "o1" in model.lower() or "o3" in model.lower())):
        base_url = base_url or "https://api.openai.com/v1"
        model = model or "gpt-4o-mini"
        api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
    elif provider in ("gemini", "google") or (not provider and "gemini" in model.lower()):
        base_url = base_url or "https://generativelanguage.googleapis.com/v1beta/openai"
        # flash-lite, not flash: the free tier's daily quota on gemini-flash-latest
        # runs out under sustained use, while flash-lite has a separate, larger
        # allowance. See app/services/gemini/config.py for the same reasoning.
        model = model or "gemini-flash-lite-latest"
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


# CareerOS's default local model. Qwen3 4B-instruct is the non-thinking variant
# (capabilities: completion, tools — no `thinking`), which is what makes its
# JSON mode reliable: there is no reasoning block to strip before parsing.
DEFAULT_LOCAL_MODEL = os.environ.get("CAREEROS_LOCAL_MODEL", "qwen3:4b-instruct")
# Kept as the local second opinion when the primary local model fails, so a bad
# response falls back to another local model before any cloud provider is used.
LOCAL_FALLBACK_MODEL = os.environ.get("CAREEROS_LOCAL_FALLBACK_MODEL", "mistral:7b-instruct")
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1")

# One switch that actually keeps the local model unloaded.
#
# CAREEROS_LOCAL_LLM was only consulted by the queue preprocessor and the
# answer engine, so turning it off still left the form reviewer and the field
# mapper building Ollama clients - and a single call is enough to pull several
# GB back into memory. Enforcing it here, where every local client is built,
# makes the flag mean what it says.
LOCAL_LLM_ENABLED = os.environ.get("CAREEROS_LOCAL_LLM", "on").strip().lower() not in (
    "off", "0", "false", "no",
)


def _is_local(base_url: str) -> bool:
    lowered = (base_url or "").lower()
    return "11434" in lowered or "localhost" in lowered or "127.0.0.1" in lowered


def _local_disabled_substitute(
    *, timeout: int, max_retries: int, confidence_threshold: float
) -> "LLMClient":
    """What to hand back when a local model was asked for but is switched off.

    Prefers Gemini when a key is configured - "skip the local model" means keep
    it off this machine's RAM, not lose the ability to reason at all. With no
    key, returns a client whose is_available() is False, which every caller
    already handles by falling back to its deterministic path.
    """
    gemini = _build_gemini_fallback(
        timeout=timeout, max_retries=max_retries, confidence_threshold=confidence_threshold
    )
    if gemini is not None:
        logger.info("CAREEROS_LOCAL_LLM=off: using Gemini instead of the local model.")
        return gemini
    logger.info("CAREEROS_LOCAL_LLM=off and no Gemini available for applications: running deterministic only.")
    return LLMClient(base_url="", model="")


def _build_local_fallback(
    *,
    primary_model: str,
    timeout: int,
    max_retries: int,
    confidence_threshold: float,
    gemini_fallback: "LLMClient | None",
    context_window: int,
) -> "LLMClient | None":
    """Mistral as the local backstop behind the primary local model.

    Returns None when the primary already *is* the fallback model, so a client
    never falls back to itself. The chain is deliberately
    local-primary -> local-fallback -> cloud: a second local model is both
    cheaper and more private than reaching for Gemini on the first failure.
    """
    if LOCAL_FALLBACK_MODEL.lower() in primary_model.lower():
        return gemini_fallback
    return LLMClient(
        base_url=OLLAMA_BASE_URL,
        model=LOCAL_FALLBACK_MODEL,
        api_key="",
        timeout=timeout,
        max_retries=max_retries,
        confidence_threshold=confidence_threshold,
        fallback=gemini_fallback,
        provider="ollama",
        context_window=context_window,
    )


def _build_gemini_fallback(*, timeout: int, max_retries: int, confidence_threshold: float) -> LLMClient | None:
    """Gemini Flash client used as the automatic fallback when the primary model fails.

    Returns None when GEMINI_API_KEY isn't configured, so callers that never
    set that key see identical behavior to before (no fallback attempted), and
    also when Gemini is switched off for the application path - everything in
    this module runs while applying to a job, so that switch applies here in
    full. Callers already handle a missing fallback by staying deterministic.
    """
    from app.services.gemini.config import applications_enabled

    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    if not gemini_key or not applications_enabled():
        return None
    return LLMClient(
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        # See the note in _resolve_llm_config: flash-lite avoids the exhausted
        # free-tier quota on flash-latest.
        model="gemini-flash-lite-latest",
        api_key=gemini_key,
        timeout=timeout,
        max_retries=max_retries,
        confidence_threshold=confidence_threshold,
        provider="gemini",
    )


def create_llm_client(settings: dict[str, Any] | None = None) -> LLMClient:
    """Create default LLM client from application assistant settings.

    Defaults to local Qwen3 via Ollama, falling back to local Mistral and then
    to Gemini Flash when the primary is unreachable or every retry fails.
    """
    settings_dict = settings or {}
    llm_config = settings_dict.get("llm", {})
    provider = str(llm_config.get("provider") or "").lower().strip()
    base_url, model, api_key = _resolve_llm_config(llm_config, default_model=DEFAULT_LOCAL_MODEL)
    timeout = llm_config.get("timeout", 60)
    max_retries = llm_config.get("maxRetries", 2)
    confidence_threshold = llm_config.get("confidenceThreshold", 0.7)
    if not LOCAL_LLM_ENABLED and _is_local(base_url):
        return _local_disabled_substitute(
            timeout=timeout, max_retries=max_retries, confidence_threshold=confidence_threshold
        )

    gemini_fallback = None if "gemini" in model.lower() else _build_gemini_fallback(
        timeout=timeout, max_retries=max_retries, confidence_threshold=confidence_threshold
    )
    context_window = int(llm_config.get("contextWindow") or DEFAULT_CONTEXT_WINDOW)
    local_fallback = _build_local_fallback(
        primary_model=model,
        timeout=timeout,
        max_retries=max_retries,
        confidence_threshold=confidence_threshold,
        gemini_fallback=gemini_fallback,
        context_window=context_window,
    )
    primary_max_retries = 0 if local_fallback is not None else max_retries

    mistral_provider_name = "ollama" if ("11434" in base_url or "ollama" in provider) else (provider or "ollama")
    primary_client = LLMClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_retries=primary_max_retries,
        confidence_threshold=confidence_threshold,
        fallback=local_fallback,
        provider=mistral_provider_name,
        context_window=context_window,
    )


    return primary_client


def create_mapping_client(settings: dict[str, Any]) -> LLMClient:
    """Text mapping model (field interpretation planner). Mistral primary, Gemini fallback."""
    llm_config = settings.get("llm", {})
    field_mapping = settings.get("fieldMapping") or {}
    model_override = field_mapping.get("mappingModel") or llm_config.get("mappingModel")

    cfg = dict(llm_config)
    if model_override:
        cfg["model"] = model_override

    base_url, model, api_key = _resolve_llm_config(cfg, default_model=DEFAULT_LOCAL_MODEL)
    timeout = llm_config.get("timeout", 90)
    max_retries = llm_config.get("maxRetries", 2)
    confidence_threshold = llm_config.get("confidenceThreshold", 0.7)
    gemini_fallback = None if "gemini" in model.lower() else _build_gemini_fallback(
        timeout=timeout, max_retries=max_retries, confidence_threshold=confidence_threshold
    )
    context_window = int(llm_config.get("contextWindow") or DEFAULT_CONTEXT_WINDOW)
    local_fallback = _build_local_fallback(
        primary_model=model,
        timeout=timeout,
        max_retries=max_retries,
        confidence_threshold=confidence_threshold,
        gemini_fallback=gemini_fallback,
        context_window=context_window,
    )
    primary_max_retries = 0 if local_fallback is not None else max_retries

    if not LOCAL_LLM_ENABLED and _is_local(base_url):
        return _local_disabled_substitute(
            timeout=timeout, max_retries=max_retries, confidence_threshold=confidence_threshold
        )

    provider = str(cfg.get("provider") or "").lower().strip()
    mistral_provider_name = "ollama" if ("11434" in base_url or "ollama" in provider) else (provider or "ollama")
    primary_client = LLMClient(
        base_url=base_url,
        model=model,
        api_key=api_key,
        timeout=timeout,
        max_retries=primary_max_retries,
        confidence_threshold=confidence_threshold,
        fallback=local_fallback,
        provider=mistral_provider_name,
        context_window=context_window,
    )


    return primary_client


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


