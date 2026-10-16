"""Onboarding and Candidate Readiness Questionnaire Router.

Provides structured onboarding questions discovered across ATS platforms (Greenhouse,
Lever, Workday, Ashby, Phenom) so new candidates can supply all essential screening
answers upfront rather than failing during live autopilot application runs.
"""

from __future__ import annotations

from typing import Any
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.store import get_kv, set_kv
from app.routers.api import db_session
from app.services.application_assistant.profile_readiness import evaluate_profile_readiness
from app.services.profile_normalizer import normalize_work_authorization

router = APIRouter(prefix="/api/onboarding", tags=["onboarding"])

ONBOARDING_SECTIONS = [
    {
        "id": "work_auth",
        "title": "Work Authorization & Sponsorship",
        "description": "Crucial legal screening questions asked by 100% of US employers.",
        "questions": [
            {
                "key": "authorizedToWorkInUS",
                "label": "Are you legally authorized to work in the United States?",
                "type": "boolean",
                "options": ["Yes", "No"],
                "required": True,
                "help": "Required by almost every job application.",
            },
            {
                "key": "sponsorship",
                "label": "Will you now or in the future require visa sponsorship for employment?",
                "type": "boolean",
                "options": ["Yes", "No"],
                "required": True,
                "help": "e.g. H-1B, O-1, or green card sponsorship.",
            },
            {
                "key": "authorizationType",
                "label": "Current Work Authorization / Visa Type",
                "type": "select",
                "options": [
                    "US Citizen",
                    "Permanent Resident / Green Card",
                    "H-1B",
                    "F-1 OPT / CPT",
                    "F-1 STEM OPT",
                    "TN Visa",
                    "E-3 Visa",
                    "L-1 / L-2",
                    "Employment Authorization Document (EAD)",
                    "Other",
                ],
                "required": False,
                "help": "Specific authorization status if applicable.",
            },
            {
                "key": "citizenshipCountry",
                "label": "Country of Citizenship / Nationality",
                "type": "text",
                "required": True,
                "help": "Needed for export control, ITAR, and immigration compliance.",
            },
        ],
    },
    {
        "id": "location_preferences",
        "title": "Location & Work Arrangement",
        "description": "Determines application eligibility based on employer geographical policies.",
        "questions": [
            {
                "key": "city",
                "label": "City",
                "type": "text",
                "required": True,
            },
            {
                "key": "state",
                "label": "State / Province",
                "type": "text",
                "required": True,
            },
            {
                "key": "zip",
                "label": "Postal / Zip Code",
                "type": "text",
                "required": True,
            },
            {
                "key": "workArrangement",
                "label": "Work Arrangement Preference",
                "type": "select",
                "options": ["Remote", "Hybrid", "Onsite", "Flexible"],
                "required": True,
            },
            {
                "key": "relocate",
                "label": "Are you willing to relocate for this role?",
                "type": "select",
                "options": ["Yes", "No", "Depends on relocation package"],
                "required": True,
            },
            {
                "key": "timezone",
                "label": "Time Zone",
                "type": "select",
                "options": [
                    "America/Los_Angeles (Pacific Time)",
                    "America/Denver (Mountain Time)",
                    "America/Chicago (Central Time)",
                    "America/New_York (Eastern Time)",
                    "Other",
                ],
                "required": True,
            },
        ],
    },
    {
        "id": "role_experience",
        "title": "Role & Compensation",
        "description": "Aligns job discovery and application salary/notice requirements.",
        "questions": [
            {
                "key": "targetRole",
                "label": "Primary Target Job Title",
                "type": "text",
                "required": True,
                "help": "e.g. Senior Software Engineer",
            },
            {
                "key": "yearsExperience",
                "label": "Total Years of Relevant Experience",
                "type": "number",
                "required": True,
            },
            {
                "key": "salaryExpectations",
                "label": "Desired Annual Salary Expectations (USD)",
                "type": "text",
                "required": False,
                "help": "e.g. $180,000 or $160,000 - $190,000",
            },
            {
                "key": "noticePeriod",
                "label": "Notice Period / Earliest Start Date",
                "type": "select",
                "options": ["Immediately", "2 weeks", "1 month", "2+ months"],
                "required": False,
            },
        ],
    },
    {
        "id": "eeo_voluntary",
        "title": "Voluntary Demographic Self-Identification (EEOC)",
        "description": "Voluntary disclosures. All questions include options to decline to self-identify.",
        "questions": [
            {
                "key": "gender",
                "label": "Gender",
                "type": "select",
                "options": ["Male", "Female", "Non-binary", "I decline to self-identify"],
                "required": False,
            },
            {
                "key": "raceEthnicity",
                "label": "Race / Ethnicity",
                "type": "select",
                "options": [
                    "Asian",
                    "Black or African American",
                    "Hispanic or Latino",
                    "White",
                    "Two or More Races",
                    "Native American or Alaska Native",
                    "Native Hawaiian or Other Pacific Islander",
                    "I decline to self-identify",
                ],
                "required": False,
            },
            {
                "key": "veteran",
                "label": "Veteran Status",
                "type": "select",
                "options": [
                    "I am not a protected veteran",
                    "I identify as one or more of the classifications of protected veteran",
                    "I decline to self-identify",
                ],
                "required": False,
            },
            {
                "key": "disability",
                "label": "Disability Status",
                "type": "select",
                "options": [
                    "No, I do not have a disability",
                    "Yes, I have a disability (or previously had a disability)",
                    "I decline to self-identify",
                ],
                "required": False,
            },
        ],
    },
    {
        "id": "application_defaults",
        "title": "Application Defaults",
        "description": "Default choices for generic survey and communication questions.",
        "questions": [
            {
                "key": "englishLevel",
                "label": "English Proficiency Level",
                "type": "select",
                "options": ["Native", "Fluent", "Proficient", "Conversational", "Basic"],
                "required": True,
            },
            {
                "key": "jobDiscoveryDefault",
                "label": "Default Answer for 'How did you hear about us?'",
                "type": "select",
                "options": ["Company careers page", "LinkedIn", "Company Website", "Online Job Board", "Other"],
                "required": True,
            },
        ],
    },
]


class OnboardingAnswersPayload(BaseModel):
    answers: dict[str, Any] = Field(default_factory=dict)


@router.get("/questions")
def get_onboarding_questions(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Return the structured questionnaire with candidate's current values pre-filled."""
    profile = get_kv(db, "profile") or {}
    readiness = evaluate_profile_readiness(profile)

    # Flatten questions to check for missing items
    flattened_keys = [q["key"] for s in ONBOARDING_SECTIONS for q in s["questions"]]
    current_values = {k: profile.get(k) for k in flattened_keys if profile.get(k) is not None}

    return {
        "success": True,
        "sections": ONBOARDING_SECTIONS,
        "currentValues": current_values,
        "isReady": readiness.ready,
        "readiness": readiness.to_dict(),
    }


@router.post("/answers")
def save_onboarding_answers(payload: OnboardingAnswersPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Save answers from onboarding questionnaire into the candidate profile."""
    profile = get_kv(db, "profile") or {}

    # Merge answers into profile
    for k, v in payload.answers.items():
        if v is not None and v != "":
            profile[k] = v

    # Normalize work authorization structure
    profile = normalize_work_authorization(profile)

    set_kv(db, "profile", profile)
    db.commit()

    readiness = evaluate_profile_readiness(profile)
    return {
        "success": True,
        "profile": profile,
        "isReady": readiness.ready,
        "readiness": readiness.to_dict(),
    }
