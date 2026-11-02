"""Job search methodology ported from ai-job-search (writing rules, verdicts, status buckets)."""

from __future__ import annotations

WRITING_STYLE_RULES = """
Cover letter writing rules (hard constraints):
- No em-dashes
- No clichés: passionate about, great fit, leverage, hit the ground running, synergy, rockstar
- No buzzwords without concrete backing
- No apologetic or hedged language
- No unverified company claims — verify independently, never from posting text alone
- Warm but direct; conversational professional; first person active voice
- Demonstrate don't state; forward-looking (tasks you can solve, not CV repetition)
- One page max; language matches posting language when specified
""".strip()

COVER_LETTER_STRUCTURE = """
Structure:
1. Opening: role + why writing + background connection (company-specific)
2. Motivation / Why This Company — first section after opening
3. Body: task-solving focus, approach/methods/tools, 3–5 outcome-oriented bullets
4. Company-specific paragraph from verified research
5. Closing: brief, confident, forward-looking
""".strip()

VERDICT_THRESHOLDS = (
    ("Strong Fit", 75),
    ("Good Fit", 60),
    ("Moderate Fit", 45),
    ("Weak Fit", 30),
    ("Poor Fit", 0),
)

DIMENSION_WEIGHTS = {
    "technical": 0.30,
    "experience": 0.25,
    "behavioral": 0.15,
    "career": 0.30,
}

OUTCOME_STATUSES = frozenset(
    {
        "in_progress",
        "hired",
        "offer_declined",
        "rejected",
        "no_response",
        "interview_only",
    }
)

TRACKER_STATUS_BUCKETS: dict[str, str] = {
    "saved": "Active",
    "autofilled": "Active",
    "submitted": "Active",
    "applied": "Active",
    "interviewing": "Interview",
    "interview": "Interview",
    "offer": "Offer",
    "hired": "Hired",
    "rejected": "Rejected/Closed",
    "no_response": "Rejected/Closed",
    "no response": "Rejected/Closed",
    "offer_declined": "Rejected/Closed",
    "offer declined": "Rejected/Closed",
    "interview_only": "Rejected/Closed",
    "withdrawn": "Rejected/Closed",
}

BUCKET_COLORS = {
    "Active": "#3b82f6",
    "Interview": "#f59e0b",
    "Offer": "#8b5cf6",
    "Hired": "#22c55e",
    "Rejected/Closed": "#ef4444",
}


def verdict_from_score(score: float) -> str:
    for label, minimum in VERDICT_THRESHOLDS:
        if score >= minimum:
            return label
    return "Poor Fit"


def normalize_status_bucket(status: str) -> str:
    return TRACKER_STATUS_BUCKETS.get(str(status or "").strip().lower(), "Active")
