"""Compare Mistral vs FreeToken performance on representative CareerOS prompts.

Measures and compares:
1. Latency (ms)
2. Valid JSON rate (%)
3. Answer completeness (presence of required schema fields)
4. Model confidence
5. Errors (network, timeout, schema failures)

Usage:
    python scripts/compare_mistral_freetoken.py
    python scripts/compare_mistral_freetoken.py --mock
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

# Ensure project root in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.config import settings
from app.services.application_assistant.llm_client import FreeTokenProvider, LLMClient

# Standard CareerOS field answering schema
SCHEMA = {
    "type": "object",
    "required": ["classification", "answer", "confidence", "safeToSubmit", "reasoning"],
    "properties": {
        "classification": {"type": "string"},
        "answer": {"type": "string"},
        "confidence": {"type": "number"},
        "safeToSubmit": {"type": "boolean"},
        "reasoning": {"type": "string"},
    },
}

SYSTEM_PROMPT = """You are an automated job application field classifier and answering assistant for CareerOS.
Analyze the provided question and candidate profile.

Rules:
1. Classify the question (e.g. WORK_AUTHORIZED, SPONSORSHIP_REQUIRED, GENDER, FREE_TEXT_EXPERIENCE, UNKNOWN).
2. Ground all answers strictly on candidate facts. Never hallucinate.
3. If ungrounded or asking for unknown confidential secrets, return answer "UNKNOWN".
4. Evaluate whether this question is safeToSubmit (true/false).

Respond ONLY with valid JSON conforming to this schema:
{
  "classification": "<QuestionType>",
  "answer": "<Selected option or concise answer>",
  "confidence": 0.0-1.0,
  "safeToSubmit": true/false,
  "reasoning": "<1-sentence justification>"
}"""

TEST_PROMPTS = [
    {
        "id": "work_auth",
        "question": "Are you legally authorized to work in the United States?",
        "context": "Candidate profile: US Citizen, authorized to work for any employer without restriction.",
    },
    {
        "id": "sponsorship",
        "question": "Will you now or in the future require immigration sponsorship for employment visa status?",
        "context": "Candidate profile: US Citizen, no sponsorship required now or in the future.",
    },
    {
        "id": "clearance",
        "question": "Do you hold an active Top Secret / SCI security clearance?",
        "context": "Candidate profile: No security clearance held.",
    },
    {
        "id": "ungrounded_secret",
        "question": "What is the corporate internal master API token for your current employer?",
        "context": "Candidate profile: Software engineer at previous company. No secret tokens shared.",
    },
    {
        "id": "free_text_experience",
        "question": "Briefly describe your experience scaling distributed backend services.",
        "context": "Candidate profile: 8 years building distributed systems in Go/Python, scaled microservices to 50k QPS with Redis and Kafka.",
    },
]


@dataclass
class PromptEvalResult:
    prompt_id: str
    latency_ms: float
    valid_json: bool
    answer_complete: bool
    confidence: float
    error: str | None = None
    raw_response: str = ""


@dataclass
class ProviderScorecard:
    provider: str
    model: str
    total_calls: int = 0
    successful_calls: int = 0
    avg_latency_ms: float = 0.0
    valid_json_rate: float = 0.0
    completeness_rate: float = 0.0
    avg_confidence: float = 0.0
    errors: list[str] = field(default_factory=list)


async def evaluate_single_prompt(
    client: LLMClient,
    prompt: dict[str, str],
    *,
    mock: bool = False,
) -> PromptEvalResult:
    user_prompt = f"Field Question: \"{prompt['question']}\"\nCandidate Context: {prompt['context']}"

    if mock:
        await asyncio.sleep(0.05 if client.provider == "freetoken" else 0.12)
        latency_ms = 45.0 if client.provider == "freetoken" else 115.0
        mock_data = {
            "classification": "WORK_AUTHORIZED" if "auth" in prompt["id"] else "EXPERIENCE",
            "answer": "Yes" if "auth" in prompt["id"] else "Scaled Go/Python microservices to 50k QPS",
            "confidence": 0.95,
            "safeToSubmit": True,
            "reasoning": "Grounded in verified candidate profile.",
        }
        return PromptEvalResult(
            prompt_id=prompt["id"],
            latency_ms=latency_ms,
            valid_json=True,
            answer_complete=True,
            confidence=0.95,
            error=None,
            raw_response=json.dumps(mock_data),
        )

    start_t = time.monotonic()
    try:
        res = await client.complete(
            user_prompt,
            system=SYSTEM_PROMPT,
            response_schema=SCHEMA,
        )
        latency_ms = (time.monotonic() - start_t) * 1000

        if not res.get("success"):
            return PromptEvalResult(
                prompt_id=prompt["id"],
                latency_ms=latency_ms,
                valid_json=False,
                answer_complete=False,
                confidence=0.0,
                error=res.get("error") or "Unknown error",
            )

        data = res.get("data")
        valid_json = isinstance(data, dict)
        required_fields = ["classification", "answer", "confidence", "safeToSubmit", "reasoning"]
        completeness = valid_json and all(k in data for k in required_fields)
        conf = float(data.get("confidence", 0.0)) if valid_json else 0.0

        return PromptEvalResult(
            prompt_id=prompt["id"],
            latency_ms=latency_ms,
            valid_json=valid_json,
            answer_complete=completeness,
            confidence=conf,
            error=None,
            raw_response=json.dumps(data) if valid_json else str(data),
        )
    except Exception as exc:
        latency_ms = (time.monotonic() - start_t) * 1000
        return PromptEvalResult(
            prompt_id=prompt["id"],
            latency_ms=latency_ms,
            valid_json=False,
            answer_complete=False,
            confidence=0.0,
            error=str(exc),
        )


async def run_comparison(
    mistral_client: LLMClient,
    freetoken_client: FreeTokenProvider,
    *,
    mock: bool = False,
) -> tuple[ProviderScorecard, ProviderScorecard]:
    mistral_results: list[PromptEvalResult] = []
    freetoken_results: list[PromptEvalResult] = []

    print("Running CareerOS Model Comparison: Mistral (Ollama) vs FreeToken\n")

    # Evaluate FreeToken
    print(f"--- Evaluating FreeToken ({freetoken_client.model}) ---")
    if not mock:
        health = await freetoken_client.check_health()
        print(f"Health Check: {health}")
        if not health.get("healthy"):
            print(f"Warning: FreeToken health check failed ({health.get('error')}).")

    for p in TEST_PROMPTS:
        res = await evaluate_single_prompt(freetoken_client, p, mock=mock)
        freetoken_results.append(res)
        status = "OK" if res.valid_json and res.answer_complete else f"ERR: {res.error}"
        print(f"  [{p['id']:<22}] {res.latency_ms:>7.1f}ms | Conf: {res.confidence:>4.2f} | {status}")

    # Evaluate Mistral
    print(f"\n--- Evaluating Mistral ({mistral_client.model}) ---")
    if not mock:
        conn = await mistral_client.test_connection()
        print(f"Connection: {conn}")

    for p in TEST_PROMPTS:
        res = await evaluate_single_prompt(mistral_client, p, mock=mock)
        mistral_results.append(res)
        status = "OK" if res.valid_json and res.answer_complete else f"ERR: {res.error}"
        print(f"  [{p['id']:<22}] {res.latency_ms:>7.1f}ms | Conf: {res.confidence:>4.2f} | {status}")

    def build_scorecard(provider_name: str, model_name: str, results: list[PromptEvalResult]) -> ProviderScorecard:
        total = len(results)
        latencies = [r.latency_ms for r in results]
        valid_jsons = sum(1 for r in results if r.valid_json)
        completes = sum(1 for r in results if r.answer_complete)
        confidences = [r.confidence for r in results if r.valid_json]
        errors = [f"{r.prompt_id}: {r.error}" for r in results if r.error]
        successes = sum(1 for r in results if r.valid_json and not r.error)

        return ProviderScorecard(
            provider=provider_name,
            model=model_name,
            total_calls=total,
            successful_calls=successes,
            avg_latency_ms=round(sum(latencies) / total, 1) if total else 0.0,
            valid_json_rate=round((valid_jsons / total) * 100, 1) if total else 0.0,
            completeness_rate=round((completes / total) * 100, 1) if total else 0.0,
            avg_confidence=round(sum(confidences) / len(confidences), 2) if confidences else 0.0,
            errors=errors,
        )

    return (
        build_scorecard("freetoken", freetoken_client.model, freetoken_results),
        build_scorecard("ollama", mistral_client.model, mistral_results),
    )


def print_comparison_table(ft_card: ProviderScorecard, mistral_card: ProviderScorecard) -> None:
    print("\n" + "=" * 80)
    print("CAREEROS LOCAL LLM BENCHMARK COMPARISON SCORECARD")
    print("=" * 80)

    header = f"{'Metric':<25} | {'FreeToken (' + ft_card.model[:12] + ')':<24} | {'Mistral (' + mistral_card.model[:12] + ')':<24}"
    print(header)
    print("-" * len(header))

    print(f"{'Avg Latency':<25} | {str(ft_card.avg_latency_ms) + ' ms':<24} | {str(mistral_card.avg_latency_ms) + ' ms':<24}")
    print(f"{'Valid JSON Rate':<25} | {str(ft_card.valid_json_rate) + '%' :<24} | {str(mistral_card.valid_json_rate) + '%':<24}")
    print(f"{'Answer Completeness':<25} | {str(ft_card.completeness_rate) + '%':<24} | {str(mistral_card.completeness_rate) + '%':<24}")
    print(f"{'Avg Confidence':<25} | {str(ft_card.avg_confidence):<24} | {str(mistral_card.avg_confidence):<24}")
    print(f"{'Successful / Total':<25} | {f'{ft_card.successful_calls}/{ft_card.total_calls}':<24} | {f'{mistral_card.successful_calls}/{mistral_card.total_calls}':<24}")
    print(f"{'Error Count':<25} | {len(ft_card.errors):<24} | {len(mistral_card.errors):<24}")
    print("=" * 80 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Compare Mistral vs FreeToken on CareerOS prompts")
    parser.add_argument("--mock", action="store_true", help="Run simulated responses to verify benchmark logic")
    parser.add_argument("--freetoken-url", default=os.environ.get("FREETOKEN_BASE_URL", "http://127.0.0.1:1919/v1"))
    parser.add_argument("--freetoken-model", default=os.environ.get("FREETOKEN_MODEL", "Qwen3.6-35B-A3B"))
    parser.add_argument("--mistral-url", default=settings.application_assistant_llm_base_url or "http://localhost:11434/v1")
    parser.add_argument("--mistral-model", default=settings.application_assistant_llm_model or "mistral-small3.2:24b")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    freetoken_client = FreeTokenProvider(
        base_url=args.freetoken_url,
        model=args.freetoken_model,
        timeout=args.timeout,
    )
    mistral_client = LLMClient(
        base_url=args.mistral_url,
        model=args.mistral_model,
        timeout=args.timeout,
        provider="ollama",
    )

    ft_card, mistral_card = asyncio.run(run_comparison(mistral_client, freetoken_client, mock=args.mock))
    print_comparison_table(ft_card, mistral_card)


if __name__ == "__main__":
    main()
