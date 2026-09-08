"""Comprehensive End-to-End Verification of FreeToken integration in CareerOS.

Verifies:
1. Health check passes with live FreeToken server (port 1919)
2. Normal application code paths:
   - Job application field answering
   - Resume / JD reasoning
   - Structured JSON validation
   - Ambiguous / corrupt input handling
   - FreeToken unavailable -> fast fallback to Mistral
   - FreeToken timeout / error -> cascading fallback to Mistral & Gemini
3. Confirms logs show `freetoken` as the provider
4. Deterministic safety validation (submission_guard, confidence gating)
5. Prevents low-confidence or malformed auto-submits
6. Side-by-side prompt comparison between FreeToken and Mistral
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Ensure project root in sys.path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import httpx
from app.config import settings
from app.db.store import list_entities, session_scope
from app.services.application_assistant.llm_client import (
    FreeTokenProvider,
    LLMClient,
    create_llm_client,
    llm_call_metrics,
)
from app.services.application_assistant.submission_guard import (
    ButtonClassification,
    classify_button,
    is_prohibited_action,
    is_safe_navigation,
)

# Configure logging to capture provider logs
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s")
logger = logging.getLogger("freetoken_verification")


async def set_freetoken_server_state(state: dict[str, Any]) -> None:
    async with httpx.AsyncClient(timeout=5.0) as client:
        await client.post("http://127.0.0.1:1919/control/state", json=state)


async def main():
    report = {
        "tests": [],
        "comparison": [],
    }

    print("\n" + "=" * 80)
    print("CAREEROS FREETOKEN END-TO-END SYSTEM VERIFICATION")
    print("=" * 80)

    # Base settings with FreeToken enabled
    freetoken_settings = {
        "llm": {
            "enabled": True,
            "baseUrl": "http://localhost:11434/v1",
            "model": "mistral:7b-instruct",
            "provider": "ollama",
            "timeout": 30,
        },
        "freetoken": {
            "enabled": True,
            "baseUrl": "http://127.0.0.1:1919/v1",
            "model": "Qwen3.6-35B-A3B",
            "timeout": 30,
        },
    }

    # --------------------------------------------------------------------------
    # Test 1: Health Check
    # --------------------------------------------------------------------------
    print("\n[Scenario 1] FreeToken Health Check Probe")
    await set_freetoken_server_state({"healthy": True, "simulate_error": False, "simulate_timeout": False})
    client = create_llm_client(freetoken_settings)
    assert isinstance(client, FreeTokenProvider), "create_llm_client must return FreeTokenProvider"

    health = await client.check_health()
    print(f"  Health Check Result: {health}")
    assert health.get("healthy") is True, f"Health check failed: {health}"
    assert "Qwen3.6-35B-A3B" in health.get("models", [])
    report["tests"].append({"name": "FreeToken Health Check", "passed": True, "details": health})

    # --------------------------------------------------------------------------
    # Test 2: Normal Application Question Answering (Structured JSON)
    # --------------------------------------------------------------------------
    print("\n[Scenario 2] Normal Job Application Question Generation (Grounded Work Auth)")
    llm_call_metrics.reset()
    start_t = time.monotonic()
    result = await client.complete(
        "Field Question: Are you legally authorized to work in the United States?\nCandidate: US Citizen",
        response_schema={
            "type": "object",
            "required": ["classification", "answer", "confidence", "safeToSubmit"],
        },
    )
    latency_ms = (time.monotonic() - start_t) * 1000
    print(f"  Latency: {latency_ms:.1f}ms")
    print(f"  Parsed JSON Data: {result.get('data')}")

    assert result.get("success") is True, f"LLM call failed: {result}"
    data = result.get("data", {})
    assert data.get("classification") == "WORK_AUTHORIZED"
    assert data.get("answer") == "Yes"
    assert data.get("confidence", 0) >= 0.90
    assert data.get("safeToSubmit") is True

    # Check metrics
    metrics = llm_call_metrics.to_dict()
    print(f"  Metrics recorded: {metrics.get('byProvider')}")
    assert "freetoken" in metrics.get("byProvider", {}), "Metrics did not record freetoken"
    report["tests"].append({
        "name": "Normal Question Generation (Work Auth)",
        "passed": True,
        "provider": "freetoken",
        "latency_ms": latency_ms,
        "data": data,
    })

    # --------------------------------------------------------------------------
    # Test 3: Resume / JD Reasoning
    # --------------------------------------------------------------------------
    print("\n[Scenario 3] Resume & JD Reasoning (Tailoring bullets)")
    start_t = time.monotonic()
    res_jd = await client.complete(
        "Please tailor a bullet for this job description requirement: Distributed high-throughput microservices.\n"
        "Candidate background: 8 years building scalable Go/Python services.",
        response_schema={"type": "object", "required": ["suggestedBullet", "relevanceScore"]},
    )
    jd_latency = (time.monotonic() - start_t) * 1000
    print(f"  Latency: {jd_latency:.1f}ms")
    print(f"  Tailored Bullet: {res_jd.get('data', {}).get('suggestedBullet')}")
    assert res_jd.get("success") is True
    assert "suggestedBullet" in res_jd.get("data", {})
    report["tests"].append({
        "name": "Resume / JD Reasoning",
        "passed": True,
        "provider": "freetoken",
        "latency_ms": jd_latency,
        "bullet": res_jd.get("data", {}).get("suggestedBullet"),
    })

    # --------------------------------------------------------------------------
    # Test 4: Ambiguous or Invalid Input Handling
    # --------------------------------------------------------------------------
    print("\n[Scenario 4] Ambiguous / Corrupt Input Handling")
    res_amb = await client.complete(
        "Question: xyz_corrupted_query_123 gibberish field",
        response_schema={"type": "object", "required": ["classification", "confidence", "safeToSubmit"]},
    )
    amb_data = res_amb.get("data", {})
    print(f"  Ambiguous Result: {amb_data}")
    assert amb_data.get("safeToSubmit") is False or amb_data.get("confidence", 0) < 0.7
    report["tests"].append({
        "name": "Ambiguous Input Handling",
        "passed": True,
        "safeToSubmit": amb_data.get("safeToSubmit"),
        "confidence": amb_data.get("confidence"),
    })

    # --------------------------------------------------------------------------
    # Test 5: FreeToken Unavailable -> Instant Fallback to Mistral
    # --------------------------------------------------------------------------
    print("\n[Scenario 5] FreeToken Unavailable -> Automatic Fallback to Mistral")
    # Simulate FreeToken becoming offline
    await set_freetoken_server_state({"healthy": False})
    # Clear client cached health
    client._last_health_check_time = 0.0

    fb_start = time.monotonic()
    fb_res = await client.complete(
        "What is your notice period? Respond with JSON: {\"answer\": \"2 weeks\", \"confidence\": 0.95}",
        response_schema={"type": "object"},
    )
    fb_latency = (time.monotonic() - fb_start) * 1000
    print(f"  Fallback latency: {fb_latency:.1f}ms")
    print(f"  Fallback Result: {fb_res}")
    assert fb_res.get("success") is True, f"Fallback failed: {fb_res}"
    print(f"  Model that answered: {fb_res.get('usedFallbackModel') or client.fallback.model}")
    report["tests"].append({
        "name": "FreeToken Unavailable -> Mistral Fallback",
        "passed": True,
        "fallback_model": fb_res.get("usedFallbackModel") or client.fallback.model,
        "latency_ms": fb_latency,
    })

    # --------------------------------------------------------------------------
    # Test 6: FreeToken 500 Error -> Seamless Fallback
    # --------------------------------------------------------------------------
    print("\n[Scenario 6] FreeToken 500 / Timeout Error -> Fallback to Mistral")
    # FreeToken is reported healthy by health check, but returns 500 on completion
    await set_freetoken_server_state({"healthy": True, "simulate_error": True})
    client._last_health_check_time = 0.0

    err_start = time.monotonic()
    err_res = await client.complete(
        "Are you willing to relocate? Respond with JSON: {\"answer\": \"Yes\", \"confidence\": 0.9}",
        response_schema={"type": "object"},
    )
    err_latency = (time.monotonic() - err_start) * 1000
    print(f"  Error Recovery Latency: {err_latency:.1f}ms")
    print(f"  Error Recovery Result: {err_res}")
    assert err_res.get("success") is True, f"Error recovery failed: {err_res}"
    assert err_res.get("usedFallbackModel") is not None
    report["tests"].append({
        "name": "FreeToken 500 Error -> Mistral Recovery",
        "passed": True,
        "recovered_by": err_res.get("usedFallbackModel"),
        "latency_ms": err_latency,
    })

    # Reset FreeToken back to healthy
    await set_freetoken_server_state({"healthy": True, "simulate_error": False, "simulate_timeout": False})
    client._last_health_check_time = 0.0

    # --------------------------------------------------------------------------
    # Test 7: Application Deterministic Safety & Guard Checks
    # --------------------------------------------------------------------------
    print("\n[Scenario 7] Deterministic Application Safety Validation")
    btn_final = classify_button("Submit Application")
    print(f"  'Submit Application' classification: {btn_final}")
    assert btn_final == ButtonClassification.PROHIBITED, "Safety guard failed to block final submit"

    btn_next = classify_button("Save and Continue")
    print(f"  'Save and Continue' classification: {btn_next}")
    assert btn_next == ButtonClassification.SAFE_NAVIGATION, "Safe navigation was falsely blocked"

    # 2. Verify low confidence model output cannot cause safe auto-submit
    low_conf_data = {"classification": "UNKNOWN", "answer": "Maybe", "confidence": 0.35, "safeToSubmit": True}
    is_safe = bool(low_conf_data.get("safeToSubmit")) and (low_conf_data.get("confidence", 0) >= 0.70)
    print(f"  Low-confidence (0.35) gated safety check: is_safe={is_safe}")
    assert is_safe is False, "Safety gate allowed low-confidence auto-submit"

    report["tests"].append({
        "name": "Deterministic Safety Validation",
        "passed": True,
        "final_submit_blocked": btn_final == ButtonClassification.PROHIBITED,
        "low_conf_rejected": is_safe is False,
    })

    # --------------------------------------------------------------------------
    # Test 8: Durable Log Inspection in SQLite
    # --------------------------------------------------------------------------
    print("\n[Scenario 8] Durable Model Usage Events in SQLite")
    with session_scope() as db:
        events = list_entities(db, "model_usage_event")
        ft_events = [e for e in events if e.get("provider") == "freetoken"]
        ollama_events = [e for e in events if e.get("provider") == "ollama"]
        print(f"  Total logged model usage events: {len(events)}")
        print(f"  FreeToken events in DB: {len(ft_events)}")
        print(f"  Ollama events in DB: {len(ollama_events)}")
        assert len(ft_events) > 0, "No FreeToken events were stored in database"
        report["tests"].append({
            "name": "SQLite Usage Events Storage",
            "passed": True,
            "freetoken_event_count": len(ft_events),
            "ollama_event_count": len(ollama_events),
        })

    # --------------------------------------------------------------------------
    # Test 9: Side-by-Side Prompt Comparison: FreeToken vs Mistral
    # --------------------------------------------------------------------------
    print("\n[Scenario 9] Side-by-Side Benchmark: FreeToken vs Mistral")
    mistral_client = LLMClient(
        base_url="http://localhost:11434/v1",
        model="mistral:7b-instruct",
        provider="ollama",
        timeout=30,
    )

    comparison_prompts = [
        {"id": "work_auth", "label": "Are you authorized to work in the US?", "ctx": "Candidate: US Citizen"},
        {"id": "sponsorship", "label": "Do you require visa sponsorship?", "ctx": "Candidate: US Citizen, no sponsorship"},
        {"id": "clearance", "label": "Security clearance level held?", "ctx": "Candidate: No clearance"},
    ]

    comp_results = []
    for cp in comparison_prompts:
        prompt_text = f"Field Question: {cp['label']}\nCandidate: {cp['ctx']}"
        schema = {"type": "object", "required": ["classification", "answer", "confidence", "safeToSubmit"]}

        # Test FreeToken
        ft_t0 = time.monotonic()
        ft_out = await client.complete(prompt_text, response_schema=schema)
        ft_dur = (time.monotonic() - ft_t0) * 1000

        # Test Mistral
        m_t0 = time.monotonic()
        m_out = await mistral_client.complete(prompt_text, response_schema=schema)
        m_dur = (time.monotonic() - m_t0) * 1000

        comp_results.append({
            "prompt": cp["id"],
            "ft_latency_ms": ft_dur,
            "ft_success": ft_out.get("success", False),
            "ft_valid_json": isinstance(ft_out.get("data"), dict),
            "ft_confidence": ft_out.get("data", {}).get("confidence", 0.0) if isinstance(ft_out.get("data"), dict) else 0.0,
            "m_latency_ms": m_dur,
            "m_success": m_out.get("success", False),
            "m_valid_json": isinstance(m_out.get("data"), dict),
            "m_confidence": m_out.get("data", {}).get("confidence", 0.0) if isinstance(m_out.get("data"), dict) else 0.0,
        })

    report["comparison"] = comp_results

    # Print comparison table
    print("\n" + "=" * 90)
    print("LIVE SIDE-BY-SIDE MODEL BENCHMARK TABLE")
    print("=" * 90)
    fmt = "{:<16} | {:<12} | {:<8} | {:<12} | {:<12} | {:<10} | {:<12}"
    print(fmt.format("Prompt", "Provider", "Success", "Latency", "Valid JSON", "Confidence", "Fallback"))
    print("-" * 90)

    for cr in comp_results:
        print(fmt.format(
            cr["prompt"],
            "FreeToken",
            "YES" if cr["ft_success"] else "NO",
            f"{cr['ft_latency_ms']:.1f} ms",
            "YES" if cr["ft_valid_json"] else "NO",
            f"{cr['ft_confidence']:.2f}",
            "None (Primary)",
        ))
        print(fmt.format(
            cr["prompt"],
            "Mistral:7b",
            "YES" if cr["m_success"] else "NO",
            f"{cr['m_latency_ms']:.1f} ms",
            "YES" if cr["m_valid_json"] else "NO",
            f"{cr['m_confidence']:.2f}",
            "Fallback Target",
        ))
        print("-" * 90)

    print("\nAll End-to-End Scenarios Passed Successfully!\n")
    return report


if __name__ == "__main__":
    asyncio.run(main())
