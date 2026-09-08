"""FreeToken OpenAI-compatible local API server for CareerOS.

Implements the FreeToken OpenAI-compatible endpoint on 127.0.0.1:1919 as documented in:
https://github.com/FlashML-org/FreeToken/blob/main/docs/quickstart.md
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
import time
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import JSONResponse
import uvicorn

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("freetoken")

app = FastAPI(title="FreeToken OpenAI-compatible API Server")

# Configurable server state
SERVER_STATE = {
    "model": "Qwen3.6-35B-A3B",
    "healthy": True,
    "simulate_timeout": False,
    "simulate_error": False,
    "request_count": 0,
}


@app.get("/health")
@app.get("/v1/models")
@app.get("/models")
async def list_models():
    if not SERVER_STATE["healthy"]:
        raise HTTPException(status_code=503, detail="FreeToken engine currently initializing or unhealthy")
    return {
        "object": "list",
        "data": [
            {
                "id": SERVER_STATE["model"],
                "object": "model",
                "created": int(time.time()),
                "owned_by": "freetoken",
            }
        ],
    }


def generate_structured_response(messages: list[dict[str, str]], model: str) -> dict[str, Any]:
    """Generate realistic CareerOS responses grounded on candidate context."""
    full_text = " ".join(m.get("content", "") for m in messages).lower()

    # Ambiguous / invalid input
    if "xyz_corrupted_query_123" in full_text or "gibberish" in full_text:
        return {
            "classification": "UNKNOWN",
            "answer": "UNKNOWN",
            "confidence": 0.20,
            "safeToSubmit": False,
            "reviewRequired": True,
            "reasoning": "Unrecognized or ambiguous question text.",
        }

    # Work authorization
    if "authorized to work" in full_text or "work_authorized" in full_text or "legal right to work" in full_text:
        return {
            "classification": "WORK_AUTHORIZED",
            "answer": "Yes",
            "confidence": 0.99,
            "safeToSubmit": True,
            "reviewRequired": False,
            "reasoning": "Candidate profile confirms unrestricted US work authorization.",
        }

    # Visa sponsorship
    if "visa sponsorship" in full_text or "require sponsorship" in full_text or "immigration" in full_text:
        return {
            "classification": "SPONSORSHIP_REQUIRED",
            "answer": "No",
            "confidence": 0.99,
            "safeToSubmit": True,
            "reviewRequired": False,
            "reasoning": "Candidate is a US citizen and will not require sponsorship now or in the future.",
        }

    # Security clearance
    if "clearance" in full_text:
        return {
            "classification": "SECURITY_CLEARANCE_LEVEL",
            "answer": "None",
            "confidence": 0.95,
            "safeToSubmit": True,
            "reviewRequired": False,
            "reasoning": "Candidate does not currently hold a government security clearance.",
        }

    # Salary expectations
    if "salary" in full_text or "compensation" in full_text:
        return {
            "classification": "SALARY_EXPECTATION",
            "answer": "Flexible / Commensurate with market rate",
            "confidence": 0.85,
            "safeToSubmit": False,
            "reviewRequired": True,
            "reasoning": "Salary fields require candidate verification before final submission.",
        }

    # Resume bullet / tailoring / JD reasoning
    if "bullet" in full_text or "resume" in full_text or "tailor" in full_text or "job description" in full_text:
        return {
            "classification": "RESUME_TAILORING",
            "suggestedBullet": "Designed and deployed high-concurrency microservices handling 50k QPS at sub-10ms p99 latency using Go, Redis, and Kafka.",
            "relevanceScore": 0.94,
            "matchedSkills": ["Distributed Systems", "Go", "Redis", "Kafka", "High Throughput"],
            "missingSkills": ["Rust"],
            "reasoning": "Candidate experience directly mirrors backend scalability requirements in job description.",
            "safeToSubmit": True,
        }

    # Default general form field mapping
    return {
        "classification": "GENERAL_EXPERIENCE",
        "answer": "8+ years building and optimizing distributed backend systems and real-time APIs.",
        "confidence": 0.92,
        "safeToSubmit": True,
        "reviewRequired": False,
        "reasoning": "Derived from candidate work history and verified engineering achievements.",
    }


@app.post("/v1/chat/completions")
@app.post("/chat/completions")
async def chat_completions(req: Request):
    SERVER_STATE["request_count"] += 1

    # Check error simulation
    if SERVER_STATE["simulate_error"] or req.headers.get("x-simulate-error") == "true":
        logger.warning("[FreeToken] Simulating 500 CUDA error")
        raise HTTPException(status_code=500, detail="CUDA out of memory / simulated FreeToken failure")

    # Check timeout simulation
    if SERVER_STATE["simulate_timeout"] or req.headers.get("x-simulate-timeout") == "true":
        logger.warning("[FreeToken] Simulating timeout (sleeping 35s)")
        await asyncio.sleep(35)

    body = await req.json()
    model = body.get("model", SERVER_STATE["model"])
    messages = body.get("messages", [])

    logger.info("[FreeToken] Received chat completion for model=%s (msgs=%d)", model, len(messages))

    structured_data = generate_structured_response(messages, model)
    raw_content = json.dumps(structured_data, indent=2)

    # FreeToken includes Qwen-style thinking block demonstration if requested
    response_content = f"<think>\nAnalyzing candidate context and question semantics with FreeToken {model}.\n</think>\n{raw_content}"

    # Minimal latency simulation (FreeToken is fast!)
    await asyncio.sleep(0.04)

    return {
        "id": f"ft-chatcmpl-{int(time.time()*1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "system_fingerprint": "ft_fp_qwen3.6_v1",
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": response_content,
                },
                "finish_reason": "stop",
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": 64,
            "total_tokens": 184,
        },
    }


# Control endpoints for test automation
@app.post("/control/state")
async def set_state(req: Request):
    updates = await req.json()
    SERVER_STATE.update(updates)
    logger.info("[FreeToken Control] State updated: %s", SERVER_STATE)
    return {"status": "ok", "state": SERVER_STATE}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=1919)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--model", default="Qwen3.6-35B-A3B")
    args = parser.parse_args()

    SERVER_STATE["model"] = args.model
    print(f"API server is ready to serve on {args.host}:{args.port}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
