"""Validate model diagnoses without interpreting malformed output as no fix needed."""

import json
import math
from typing import Any


def parse_healing_response(result: dict[str, Any]) -> dict[str, Any]:
    if result.get("success") is False:
        raise ValueError(str(result.get("error") or "Model request failed"))
    raw = result.get("data") or result.get("text")
    if isinstance(raw, dict):
        parsed = raw
    elif isinstance(raw, str):
        # Decode one JSON object, allowing a prose/fenced preamble without a
        # greedy regex swallowing a second object or trailing commentary.
        start = raw.find("{")
        if start < 0:
            raise ValueError("Model returned no JSON diagnosis")
        parsed, _ = json.JSONDecoder().raw_decode(raw[start:])
    else:
        raise ValueError("Model returned an empty diagnosis")
    if parsed.get("patchType") not in {"no_fix", "function_replace"}:
        raise ValueError("Unsupported diagnosis patch type")
    confidence = parsed.get("confidence")
    if isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
        raise ValueError("Diagnosis confidence must be numeric")
    if not math.isfinite(confidence) or not 0 <= confidence <= 1:
        raise ValueError("Diagnosis confidence must be between zero and one")
    if not isinstance(parsed.get("analysis"), str):
        raise ValueError("Diagnosis must include an analysis")
    return parsed
