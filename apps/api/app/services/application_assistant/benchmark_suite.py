"""CareerOS LLM Benchmark Engine: sequential runner and evaluator for local Ollama & Gemini models."""

from __future__ import annotations

import asyncio
import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx

from app.services.application_assistant.benchmark_dataset import (
    BENCHMARK_CASES,
    BENCHMARK_PROFILE,
    BENCHMARK_RESUME_TEXT,
)

SYSTEM_BENCHMARK_INSTRUCTION = """You are an automated job application field classifier and answering assistant for CareerOS.
Analyze the provided job application question, candidate profile, and resume text.

Rules:
1. Classify the question into a QuestionType (e.g. WORK_AUTHORIZED, SPONSORSHIP_REQUIRED, PERMANENT_WORK_AUTHORIZATION, CITIZENSHIP, EXPORT_CONTROL, SECURITY_CLEARANCE_LEVEL, SECURITY_CLEARANCE_ELIGIBILITY, GENDER, RACE, ETHNICITY_HISPANIC_LATINO, VETERAN_STATUS, DISABILITY, LOCATION, STATE, ZIP, YEARS_EXPERIENCE, DEGREE, GPA, NOTICE_PERIOD, RELOCATE, COMPANY_HISTORY, SMS_CONSENT, ACCURACY_CONFIRMATION, GITHUB, FREE_TEXT_EXPERIENCE, FREE_TEXT_WHY_COMPANY, FREE_TEXT_TECHNICAL, UNKNOWN).
2. If available options are given, choose the EXACT string match from the options list that reflects candidate's ground truth.
3. If the question asks for information not in the candidate's profile/resume, or asks for ungrounded internal IDs/secrets, you MUST return answer "UNKNOWN" and classification "UNKNOWN". Never guess or hallucinate sensitive or demographic details.
4. For demographic questions where profile is undisclosed, select the "Decline to answer" / "Prefer not to say" option or return "UNKNOWN".
5. For free-text questions, summarize the candidate's actual experience directly from the resume in first person (2-3 concise sentences). Never invent employers or metrics.
6. Evaluate whether this question is SAFE_TO_SUBMIT or requires REVIEW_REQUIRED.

Respond ONLY with valid JSON conforming to this schema:
{
  "classification": "<QuestionType>",
  "answer": "<Selected option or concise answer or UNKNOWN>",
  "confidence": 0.95,
  "safeToSubmit": true,
  "reviewRequired": false,
  "reasoning": "<Concise 1-sentence explanation>"
}"""


@dataclass
class TestCaseResult:
    testId: str
    question: str
    category: str
    isCritical: bool
    expectedClassification: str
    actualClassification: str
    expectedAnswer: str
    actualAnswer: str
    modelConfidence: float
    correctClassification: bool
    correctAnswer: bool
    hallucinated: bool
    abstained: bool
    safeToSubmit: bool
    reviewRequired: bool
    falseSafeToSubmit: bool
    latencyMs: int
    rawOutput: str = ""
    error: str = ""


@dataclass
class ModelScorecard:
    model: str
    provider: str
    totalCases: int
    classificationAccuracy: float
    answerAccuracy: float
    criticalFieldAccuracy: float
    hallucinationRate: float
    correctAbstentionRate: float
    structuredJsonSuccessRate: float
    falseSafeToSubmitRate: float
    reviewRequiredRate: float
    averageLatencyMs: int
    totalPromptTokens: int
    totalCompletionTokens: int
    estimatedCostPer100Apps: float
    estimatedCostPer1000Apps: float
    estimatedCostPer10000Apps: float
    overallBenchmarkScore: float
    verifiedBadgePercent: int
    results: list[dict[str, Any]] = field(default_factory=list)


async def unload_ollama_model(model_name: str, base_url: str = "http://localhost:11434") -> None:
    """Explicitly unloads model from VRAM by setting keep_alive=0."""
    try:
        url = f"{base_url.rstrip('/')}/api/generate"
        payload = {"model": model_name, "keep_alive": 0}
        async with httpx.AsyncClient(timeout=10) as client:
            await client.post(url, json=payload)
    except Exception:
        pass


def _normalize_text(val: str) -> str:
    if not val:
        return ""
    v = val.strip().lower()
    v = re.sub(r"[^\w\s]", "", v)
    return " ".join(v.split())


def evaluate_answer_match(
    actual: str,
    expected: str,
    case: dict[str, Any],
) -> tuple[bool, bool, bool]:
    """Returns (is_correct, is_hallucinated, is_abstained)."""
    norm_actual = _normalize_text(actual)
    norm_expected = _normalize_text(expected)

    is_abstained = norm_actual in ("unknown", "prefer not to say", "prefer not to answer", "decline to answer", "decline", "none", "na", "not applicable")

    if expected.upper() == "UNKNOWN":
        if is_abstained or "decline" in norm_actual or "prefer not" in norm_actual or "unknown" in norm_actual:
            return True, False, True
        return False, True, False

    # Check hallucination traps
    traps = case.get("hallucinationTraps") or []
    for trap in traps:
        if trap.lower() in actual.lower():
            return False, True, is_abstained

    # Direct match or option match
    if norm_actual == norm_expected:
        return True, False, is_abstained

    if norm_expected in norm_actual or norm_actual in norm_expected:
        return True, False, is_abstained

    # For free-text grounded checks
    keywords = case.get("groundingKeywords") or []
    if keywords:
        matches = sum(1 for kw in keywords if kw.lower() in actual.lower())
        if matches >= max(1, len(keywords) // 2):
            return True, False, is_abstained

    return False, False, is_abstained


class BenchmarkRunner:
    """Executes benchmark cases against Ollama or Gemini endpoints."""

    def __init__(self, cases: list[dict[str, Any]] | None = None):
        self.cases = cases or BENCHMARK_CASES

    async def call_gemini(
        self,
        prompt: str,
        system_instruction: str,
        api_key: str,
        model: str = "gemini-3.6-flash",
    ) -> tuple[dict[str, Any] | None, str, int, int, int]:
        """Calls Gemini API directly using official generateContent endpoint."""
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
        payload = {
            "contents": [{"parts": [{"text": prompt}]}],
            "systemInstruction": {"parts": [{"text": system_instruction}]},
            "generationConfig": {
                "temperature": 0.1,
                "responseMimeType": "application/json",
            },
        }
        start_t = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=90) as client:
                resp = await client.post(url, json=payload)
                elapsed_ms = int((time.perf_counter() - start_t) * 1000)
                if resp.status_code != 200:
                    return None, f"HTTP {resp.status_code}: {resp.text[:200]}", elapsed_ms, 0, 0

            data = resp.json()
            usage = data.get("usageMetadata", {})
            prompt_tokens = usage.get("promptTokenCount", 0)
            completion_tokens = usage.get("candidatesTokenCount", 0)

            candidates = data.get("candidates", [])
            if not candidates:
                return None, "No candidates returned", elapsed_ms, prompt_tokens, completion_tokens

            text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            # Strip code fences if present
            cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip(), flags=re.MULTILINE)
            cleaned = re.sub(r"\s*```$", "", cleaned.strip(), flags=re.MULTILINE).strip()

            try:
                parsed = json.loads(cleaned)
                return parsed, text, elapsed_ms, prompt_tokens, completion_tokens
            except Exception:
                m = re.search(r"\{.*\}", cleaned, re.DOTALL)
                if m:
                    try:
                        return json.loads(m.group(0)), text, elapsed_ms, prompt_tokens, completion_tokens
                    except Exception:
                        pass
                return None, f"JSON parse error: {cleaned[:150]}", elapsed_ms, prompt_tokens, completion_tokens
        except httpx.TimeoutException:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return None, "Gemini Request Timeout", elapsed_ms, 0, 0
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return None, f"Gemini Error: {exc}", elapsed_ms, 0, 0

    async def call_ollama(
        self,
        prompt: str,
        system_instruction: str,
        model: str,
        base_url: str = "http://localhost:11434",
    ) -> tuple[dict[str, Any] | None, str, int, int, int]:
        """Calls local Ollama chat completion."""
        url = f"{base_url.rstrip('/')}/api/chat"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 256,
            },
        }
        start_t = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(url, json=payload)
                elapsed_ms = int((time.perf_counter() - start_t) * 1000)
                if resp.status_code != 200:
                    return None, f"HTTP {resp.status_code}: {resp.text[:200]}", elapsed_ms, 0, 0

                data = resp.json()
                prompt_tokens = data.get("prompt_eval_count", 0)
                completion_tokens = data.get("eval_count", 0)
                content = data.get("message", {}).get("content", "")

                # Strip thinking tags if present
                cleaned = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                try:
                    parsed = json.loads(cleaned)
                    return parsed, cleaned, elapsed_ms, prompt_tokens, completion_tokens
                except Exception:
                    # Try finding JSON block
                    m = re.search(r"\{.*\}", cleaned, re.DOTALL)
                    if m:
                        try:
                            return json.loads(m.group(0)), cleaned, elapsed_ms, prompt_tokens, completion_tokens
                        except Exception:
                            pass
                    return None, f"JSON parse error: {cleaned[:150]}", elapsed_ms, prompt_tokens, completion_tokens
        except httpx.TimeoutException:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return None, "Request timeout", elapsed_ms, 0, 0
        except Exception as exc:
            elapsed_ms = int((time.perf_counter() - start_t) * 1000)
            return None, str(exc), elapsed_ms, 0, 0

    async def benchmark_model(
        self,
        model_name: str,
        provider: str,
        api_key: str = "",
        base_url: str = "http://localhost:11434",
    ) -> ModelScorecard:
        """Runs all test cases against a specific model sequentially."""
        results: list[TestCaseResult] = []
        total_prompt_tokens = 0
        total_completion_tokens = 0
        json_successes = 0

        print(f"[{provider.upper()}] Benchmarking {model_name} on {len(self.cases)} test cases...", flush=True)
        for idx, case in enumerate(self.cases, start=1):
            print(f"  [{idx}/{len(self.cases)}] {model_name} -> {case['question'][:45]}...", flush=True)

            user_prompt = (
                f"Candidate Profile:\n{json.dumps(BENCHMARK_PROFILE, indent=2)}\n\n"
                f"Resume Snippet:\n{BENCHMARK_RESUME_TEXT.strip()}\n\n"
                f"Question: {case['question']}\n"
                f"Available Options: {json.dumps(case.get('options', []))}\n"
                f"Is Ambiguous / Ungrounded: {case.get('ambiguous', False)}\n"
            )

            if provider == "gemini":
                parsed, raw_text, latency_ms, p_tok, c_tok = await self.call_gemini(
                    prompt=user_prompt,
                    system_instruction=SYSTEM_BENCHMARK_INSTRUCTION,
                    api_key=api_key,
                    model=model_name,
                )
            else:
                parsed, raw_text, latency_ms, p_tok, c_tok = await self.call_ollama(
                    prompt=user_prompt,
                    system_instruction=SYSTEM_BENCHMARK_INSTRUCTION,
                    model=model_name,
                    base_url=base_url,
                )

            total_prompt_tokens += p_tok
            total_completion_tokens += c_tok

            actual_classification = ""
            actual_answer = ""
            confidence = 0.0
            safe_to_submit = False
            review_req = True
            error_str = ""

            if parsed and isinstance(parsed, dict):
                json_successes += 1
                actual_classification = str(parsed.get("classification") or "").upper()
                actual_answer = str(parsed.get("answer") or "")
                confidence = float(parsed.get("confidence") or 0.5)
                safe_to_submit = bool(parsed.get("safeToSubmit", False))
                review_req = bool(parsed.get("reviewRequired", False))
            else:
                error_str = raw_text

            # Evaluate Classification Accuracy
            exp_class = case["expectedClassification"].upper()
            class_correct = (
                actual_classification == exp_class
                or (exp_class in actual_classification)
                or (actual_classification == "UNKNOWN" and case.get("ambiguous", False))
            )

            # Evaluate Answer Accuracy, Hallucination, and Abstention
            ans_correct, is_hallucinated, is_abstained = evaluate_answer_match(
                actual=actual_answer,
                expected=case["expectedAnswer"],
                case=case,
            )

            # False SAFE_TO_SUBMIT: when model says safe=true on critical mistake or ungrounded question
            false_safe = False
            if safe_to_submit:
                if case["isCritical"] and not ans_correct:
                    false_safe = True
                elif case.get("ambiguous") and not is_abstained:
                    false_safe = True

            results.append(
                TestCaseResult(
                    testId=case["id"],
                    question=case["question"],
                    category=case["category"],
                    isCritical=case["isCritical"],
                    expectedClassification=case["expectedClassification"],
                    actualClassification=actual_classification,
                    expectedAnswer=case["expectedAnswer"],
                    actualAnswer=actual_answer,
                    modelConfidence=confidence,
                    correctClassification=class_correct,
                    correctAnswer=ans_correct,
                    hallucinated=is_hallucinated,
                    abstained=is_abstained,
                    safeToSubmit=safe_to_submit,
                    reviewRequired=review_req,
                    falseSafeToSubmit=false_safe,
                    latencyMs=latency_ms,
                    rawOutput=raw_text[:300],
                    error=error_str,
                )
            )

        # Compute scorecard aggregates
        n = len(results)
        class_acc = sum(1 for r in results if r.correctClassification) / n
        ans_acc = sum(1 for r in results if r.correctAnswer) / n

        crit_cases = [r for r in results if r.isCritical]
        crit_acc = (sum(1 for r in crit_cases if r.correctAnswer) / len(crit_cases)) if crit_cases else 1.0

        hallucination_rate = sum(1 for r in results if r.hallucinated) / n
        ambig_cases = [r for r in results if self.cases[[c['id'] for c in self.cases].index(r.testId)].get('ambiguous')]
        abstention_rate = (sum(1 for r in ambig_cases if r.abstained) / len(ambig_cases)) if ambig_cases else 1.0

        json_rate = json_successes / n
        false_safe_rate = sum(1 for r in results if r.falseSafeToSubmit) / n
        review_req_rate = sum(1 for r in results if r.reviewRequired) / n
        avg_latency = int(sum(r.latencyMs for r in results) / n)

        # Weighted composite score (0 - 100):
        # Critical-field accuracy is weighted heavily (40%), Answer accuracy (25%), Classification (15%),
        # Hallucination penalty (10%), False Safe penalty (10%).
        composite_score = (
            (crit_acc * 40.0)
            + (ans_acc * 25.0)
            + (class_acc * 15.0)
            + (abstention_rate * 10.0)
            + (json_rate * 10.0)
            - (hallucination_rate * 30.0)
            - (false_safe_rate * 40.0)
        )
        composite_score = max(0.0, min(100.0, composite_score))
        verified_pct = int(round(composite_score))

        # Gemini 2.5 Flash pricing: $0.075 per 1M input tokens, $0.30 per 1M output tokens
        # 1 job application averages ~15 form questions
        cost_per_token_in = 0.075 / 1_000_000 if provider == "gemini" else 0.0
        cost_per_token_out = 0.30 / 1_000_000 if provider == "gemini" else 0.0
        app_cost_unit = (total_prompt_tokens / n * cost_per_token_in + total_completion_tokens / n * cost_per_token_out) * 15

        return ModelScorecard(
            model=model_name,
            provider=provider,
            totalCases=n,
            classificationAccuracy=round(class_acc * 100, 1),
            answerAccuracy=round(ans_acc * 100, 1),
            criticalFieldAccuracy=round(crit_acc * 100, 1),
            hallucinationRate=round(hallucination_rate * 100, 1),
            correctAbstentionRate=round(abstention_rate * 100, 1),
            structuredJsonSuccessRate=round(json_rate * 100, 1),
            falseSafeToSubmitRate=round(false_safe_rate * 100, 1),
            reviewRequiredRate=round(review_req_rate * 100, 1),
            averageLatencyMs=avg_latency,
            totalPromptTokens=total_prompt_tokens,
            totalCompletionTokens=total_completion_tokens,
            estimatedCostPer100Apps=round(app_cost_unit * 100, 4),
            estimatedCostPer1000Apps=round(app_cost_unit * 1000, 3),
            estimatedCostPer10000Apps=round(app_cost_unit * 10000, 2),
            overallBenchmarkScore=round(composite_score, 1),
            verifiedBadgePercent=verified_pct,
            results=[asdict(r) for r in results],
        )


async def run_full_sequential_benchmark(
    gemini_api_key: str,
    models_to_test: list[dict[str, str]] | None = None,
    output_path: str = "data/benchmark_results.json",
) -> dict[str, Any]:
    """Runs local models sequentially, unloads each before running next, then runs Gemini API."""
    runner = BenchmarkRunner()

    default_models = [
        {"model": "qwen2.5:3b", "provider": "ollama"},
        {"model": "qwen3:4b", "provider": "ollama"},
        {"model": "gemma3:12b", "provider": "ollama"},
        {"model": "mistral-small3.2:24b", "provider": "ollama"},
        {"model": "gemini-3.6-flash", "provider": "gemini"},
    ]

    models = models_to_test or default_models
    scorecards: list[ModelScorecard] = []

    for item in models:
        model_name = item["model"]
        provider = item["provider"]

        scorecard = await runner.benchmark_model(
            model_name=model_name,
            provider=provider,
            api_key=gemini_api_key,
        )
        scorecards.append(scorecard)

        # Incrementally save results so far
        intermediate_leaderboard = sorted(scorecards, key=lambda s: s.overallBenchmarkScore, reverse=True)
        out_file = Path(output_path)
        out_file.parent.mkdir(parents=True, exist_ok=True)
        temp_payload = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "totalTestCases": len(BENCHMARK_CASES),
            "leaderboard": [asdict(s) for s in intermediate_leaderboard],
            "inProgress": True,
        }
        out_file.write_text(json.dumps(temp_payload, indent=2), encoding="utf-8")

        # Unload local model completely from VRAM before moving to next
        if provider == "ollama":
            await unload_ollama_model(model_name)
            await asyncio.sleep(2)

    # Sort leaderboard by overall score descending
    scorecards_sorted = sorted(scorecards, key=lambda s: s.overallBenchmarkScore, reverse=True)

    # Compile final comparison summary & recommendations
    gemini_card = next((s for s in scorecards if s.provider == "gemini"), None)
    local_cards = [s for s in scorecards if s.provider == "ollama"]
    best_local = max(local_cards, key=lambda s: s.overallBenchmarkScore) if local_cards else None
    fastest_model = min(scorecards, key=lambda s: s.averageLatencyMs)
    safest_model = max(scorecards, key=lambda s: (s.criticalFieldAccuracy, -s.falseSafeToSubmitRate, -s.hallucinationRate))

    output_payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "totalTestCases": len(BENCHMARK_CASES),
        "leaderboard": [asdict(s) for s in scorecards_sorted],
        "recommendation": {
            "bestOverallModel": scorecards_sorted[0].model,
            "bestLocalModel": best_local.model if best_local else "None",
            "fastestModel": fastest_model.model,
            "safestModel": safest_model.model,
            "modelRankings": [
                {
                    "model": s.model,
                    "provider": s.provider,
                    "score": s.overallBenchmarkScore,
                    "verifiedBadge": f"{s.verifiedBadgePercent}% verified",
                    "criticalAccuracy": f"{s.criticalFieldAccuracy}%",
                    "latency": f"{s.averageLatencyMs}ms",
                }
                for s in scorecards_sorted
            ],
            "costProjections": {
                "geminiModel": gemini_card.model if gemini_card else "gemini-2.5-flash",
                "costPer100Apps": f"${gemini_card.estimatedCostPer100Apps:.4f}" if gemini_card else "$0.00",
                "costPer1000Apps": f"${gemini_card.estimatedCostPer1000Apps:.3f}" if gemini_card else "$0.00",
                "costPer10000Apps": f"${gemini_card.estimatedCostPer10000Apps:.2f}" if gemini_card else "$0.00",
            },
        },
    }

    out_file = Path(output_path)
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(output_payload, indent=2), encoding="utf-8")

    return output_payload
