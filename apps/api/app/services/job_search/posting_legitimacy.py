"""Block G — posting legitimacy checks (career-ops scam/ghost signals)."""

from __future__ import annotations

import re
from typing import Any

SUSPICIOUS_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:send|pay|wire|transfer)\s+(?:money|fee|usd|\$)\b", "Requests payment or fees"),
    (r"\b(?:telegram|whatsapp only|text only)\b", "Off-platform contact only"),
    (r"\b(?:crypto|bitcoin|usdt)\b", "Crypto payment mention"),
    (r"\b(?:pyramid|mlm|multi[\s-]?level)\b", "MLM-style language"),
    (r"\b(?:earn\s+\$?\d{2,3}k?\s*(?:per|\/)\s*(?:day|week)|\$?\d{3,}\s*(?:\/|per)\s*hour)\b", "Unrealistic pay claim"),
    (r"\bno\s+experience\s+(?:needed|required)\s+.*\b(?:\$|six[\s-]?figure)\b", "High pay + no experience"),
    (r"\b(?:training\s+fee|application\s+fee|background\s+check\s+fee)\b", "Applicant-paid fees"),
]

CAUTION_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:stealth|undisclosed|confidential)\s+(?:startup|company)\b", "Stealth / undisclosed employer"),
    (r"\b(?:urgent|immediate\s+start|asap)\s+(?:hire|need)\b", "Extreme urgency language"),
    (r"\b(?:email\s+(?:resume|cv)\s+to|gmail\.com|yahoo\.com|proton\.me)\b", "Personal email apply flow"),
    (r"\b(?:100%\s+remote).{0,40}\b(?:worldwide|anywhere)\b", "Very broad remote + vague scope"),
    (r"\b(?:copy[\s-]?paste|template)\s+(?:cover\s+letter|application)\b", "Low-effort application spam signal"),
]

TRUST_PATTERNS: list[tuple[str, str]] = [
    (r"\b(?:greenhouse|lever|ashby|workday|smartrecruiters)\b", "Known ATS host"),
    (r"\b(?:401k|health\s+insurance|benefits|equity)\b", "Standard benefits mentioned"),
    (r"\b(?:eeo|equal\s+opportunity|affirmative\s+action)\b", "EEO statement present"),
]


def check_posting_legitimacy(
    *,
    title: str,
    description: str,
    url: str = "",
    company: str = "",
) -> dict[str, Any]:
    text = f"{title}\n{description}\n{url}\n{company}".lower()
    signals: list[str] = []
    score = 72

    for pattern, message in SUSPICIOUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            signals.append(message)
            score -= 22

    for pattern, message in CAUTION_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            signals.append(message)
            score -= 10

    for pattern, message in TRUST_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            score += 4

    if company.strip().lower() in {"", "unknown", "unknown company"}:
        signals.append("Company name missing or generic")
        score -= 8

    if len(description.strip()) < 120:
        signals.append("Very short job description")
        score -= 12

    score = max(0, min(100, score))
    if score >= 70 and not any("payment" in s.lower() or "fee" in s.lower() for s in signals):
        verdict = "trusted"
    elif score >= 45:
        verdict = "caution"
    else:
        verdict = "suspicious"

    return {
        "verdict": verdict,
        "score": score,
        "signals": signals[:5],
        "block": "G",
    }
