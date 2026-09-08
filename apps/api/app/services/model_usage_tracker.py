"""Durable, cross-restart logging of which LLM answered a given call —
local Ollama (Mistral) vs OpenRouter (Gemini) — so usage/success can be
compared later in Analytics. Complements (does not replace) the existing
process-memory-only `LLMCallMetrics` in `application_assistant/llm_client.py`.

Fire-and-forget: a logging failure must never break the LLM call it's
instrumenting.
"""

from __future__ import annotations

from typing import Any, Literal

from app.db.store import new_id, now_iso, session_scope, upsert_entity

ENTITY_MODEL_USAGE_EVENT = "model_usage_event"

Provider = Literal["ollama", "openrouter", "freetoken", "gemini", "openai"] | str


def log_model_usage(
    *,
    provider: Provider | str,
    model: str,
    task: str,
    success: bool,
    latency_ms: float | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    try:
        with session_scope() as db:
            upsert_entity(
                db,
                ENTITY_MODEL_USAGE_EVENT,
                {
                    "id": new_id("modelusage_"),
                    "provider": provider,
                    "model": model,
                    "task": task,
                    "success": bool(success),
                    "latencyMs": latency_ms,
                    "metadata": metadata or {},
                    "createdAt": now_iso(),
                },
            )
    except Exception:
        # Never let instrumentation break the real LLM call site it wraps.
        pass


def summarize_model_usage() -> dict[str, Any]:
    """Aggregate real model_usage_event records — no fabricated numbers."""
    from collections import defaultdict

    from app.db.store import list_entities

    with session_scope() as db:
        events = list_entities(db, ENTITY_MODEL_USAGE_EVENT)

    by_key: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {"calls": 0, "successes": 0, "failures": 0, "latencies": [], "byTask": defaultdict(lambda: {"calls": 0, "successes": 0})}
    )

    for ev in events:
        provider = ev.get("provider", "unknown")
        model = ev.get("model", "unknown")
        key = (provider, model)
        bucket = by_key[key]
        bucket["calls"] += 1
        if ev.get("success"):
            bucket["successes"] += 1
        else:
            bucket["failures"] += 1
        latency = ev.get("latencyMs")
        if isinstance(latency, (int, float)):
            bucket["latencies"].append(latency)
        task = ev.get("task", "unknown")
        task_bucket = bucket["byTask"][task]
        task_bucket["calls"] += 1
        if ev.get("success"):
            task_bucket["successes"] += 1

    result = []
    for (provider, model), bucket in by_key.items():
        calls = bucket["calls"]
        latencies = bucket["latencies"]
        result.append(
            {
                "provider": provider,
                "model": model,
                "totalCalls": calls,
                "successCount": bucket["successes"],
                "failureCount": bucket["failures"],
                "successRate": round(bucket["successes"] / calls, 4) if calls else None,
                "avgLatencyMs": round(sum(latencies) / len(latencies), 1) if latencies else None,
                "byTask": {
                    task: {
                        "calls": t["calls"],
                        "successRate": round(t["successes"] / t["calls"], 4) if t["calls"] else None,
                    }
                    for task, t in bucket["byTask"].items()
                },
            }
        )

    result.sort(key=lambda r: -r["totalCalls"])
    return {"totalEvents": len(events), "byProviderModel": result}
