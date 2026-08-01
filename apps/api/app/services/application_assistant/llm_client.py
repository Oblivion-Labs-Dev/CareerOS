"""Optional local LLM client for Application Assistant."""

from __future__ import annotations

import json
from typing import Any

import httpx


class LLMClient:
    """Provider-agnostic OpenAI-compatible LLM client."""

    def __init__(
        self,
        *,
        base_url: str = "http://localhost:1234/v1",
        model: str = "",
        api_key: str = "",
        timeout: int = 30,
        max_retries: int = 2,
        confidence_threshold: float = 0.7,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_retries = max_retries
        self.confidence_threshold = confidence_threshold

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
                    return {"success": True, "models": models}
                return {"success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    async def chat(
        self,
        messages: list[dict[str, str]],
        *,
        system: str = "",
    ) -> dict[str, Any]:
        """Multi-turn chat completion."""
        if not self.enabled:
            return {"success": False, "error": "LLM not configured"}

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
        """
        Send a completion request with structured JSON output validation.
        Never used for Playwright control or sensitive answers.
        """
        if not self.enabled:
            return {"success": False, "error": "LLM not configured"}

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


def create_llm_client(settings: dict[str, Any]) -> LLMClient:
    """Create default LLM client from application assistant settings."""
    llm_config = settings.get("llm", {})
    return LLMClient(
        base_url=llm_config.get("baseUrl", "http://localhost:11434/v1"),
        model=llm_config.get("model", "qwen3:8b"),
        api_key=llm_config.get("apiKey", ""),
        timeout=llm_config.get("timeout", 60),
        max_retries=llm_config.get("maxRetries", 2),
        confidence_threshold=llm_config.get("confidenceThreshold", 0.7),
    )


def create_mapping_client(settings: dict[str, Any]) -> LLMClient:
    """Text mapping model (field interpretation planner)."""
    llm_config = settings.get("llm", {})
    field_mapping = settings.get("fieldMapping") or {}
    model = (
        field_mapping.get("mappingModel")
        or llm_config.get("mappingModel")
        or llm_config.get("model", "qwen3:8b")
    )
    return LLMClient(
        base_url=llm_config.get("baseUrl", "http://localhost:11434/v1"),
        model=model,
        api_key=llm_config.get("apiKey", ""),
        timeout=llm_config.get("timeout", 90),
        max_retries=llm_config.get("maxRetries", 2),
        confidence_threshold=llm_config.get("confidenceThreshold", 0.7),
    )


def create_vision_client(settings: dict[str, Any]) -> LLMClient:
    """Optional vision model for ambiguous fields."""
    llm_config = settings.get("llm", {})
    field_mapping = settings.get("fieldMapping") or {}
    model = field_mapping.get("visionModel") or llm_config.get("visionModel") or ""
    if not model or not field_mapping.get("visionEnabled", False):
        return LLMClient(base_url="", model="")
    return LLMClient(
        base_url=llm_config.get("baseUrl", "http://localhost:11434/v1"),
        model=model,
        api_key=llm_config.get("apiKey", ""),
        timeout=llm_config.get("timeout", 120),
        max_retries=llm_config.get("maxRetries", 1),
        confidence_threshold=llm_config.get("confidenceThreshold", 0.7),
    )
