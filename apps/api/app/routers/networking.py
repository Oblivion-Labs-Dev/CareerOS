"""Networking: a per-company workspace over the existing referral-contact CRM.

Deliberately does NOT do automated contact/recruiter discovery — there's no
people-search or verified-email-lookup API wired up (that's a paid service a
competitor like Tsenta uses; we don't have budget/credentials for one here).
Contacts come from the existing `referral` entities (added by the user, or via
the Referrals page) or from a name the user types in on this page. What this
module adds on top: a single company-scoped view of jobs + contacts, and an
LLM-drafted (never auto-sent) outreach email + LinkedIn note per contact.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.store import get_kv, new_id, now_iso, session_scope, upsert_entity
from app.services.application_assistant.persistence import (
    get_discovered_job,
    list_application_drafts,
    list_discovered_jobs,
)
from app.services.llm import call_openrouter_json

router = APIRouter(prefix="/networking", tags=["networking"])


def db_session() -> Generator[Session, None, None]:
    with session_scope() as db:
        yield db


class AddContactPayload(BaseModel):
    contactName: str
    roleTitle: str | None = None
    email: str | None = None
    linkedin: str | None = None
    relationship: str | None = None
    notes: str | None = None


class DraftOutreachPayload(BaseModel):
    contactName: str
    contactRole: str | None = None
    companyName: str
    jobId: str | None = None


def _norm(name: str) -> str:
    return (name or "").strip().lower()


@router.get("/companies")
def list_companies(db: Session = Depends(db_session)) -> dict[str, Any]:
    """Companies to show in the picker: anywhere the user has an application/draft
    OR an existing contact — so a workspace can start from either direction."""
    from app.db.store import list_entities

    seen: dict[str, str] = {}
    for draft in list_application_drafts(db, exclude_demo=True):
        company = str(draft.get("companyName") or "").strip()
        if company and _norm(company) not in seen:
            seen[_norm(company)] = company
    for referral in list_entities(db, "referral"):
        company = str(referral.get("companyName") or "").strip()
        if company and _norm(company) not in seen:
            seen[_norm(company)] = company
    return {"success": True, "companies": sorted(seen.values(), key=str.lower)}


@router.get("/company/{company_name}")
def get_company_workspace(company_name: str, db: Session = Depends(db_session)) -> dict[str, Any]:
    from app.db.store import list_entities

    target = _norm(company_name)

    drafts = [
        d for d in list_application_drafts(db, exclude_demo=True)
        if _norm(str(d.get("companyName") or "")) == target
    ]
    discovered = [
        j for j in list_discovered_jobs(db, active_only=False, exclude_demo=True)
        if _norm(str(j.get("company") or "")) == target
    ]
    contacts = [
        r for r in list_entities(db, "referral")
        if _norm(str(r.get("companyName") or "")) == target
    ]

    return {
        "success": True,
        "companyName": company_name,
        "applications": drafts,
        "discoveredJobs": discovered,
        "contacts": contacts,
    }


@router.post("/company/{company_name}/contacts")
def add_company_contact(company_name: str, payload: AddContactPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Add a manually-found contact. Stored as a `referral` entity so it shows up
    on both the Networking workspace and the existing Referrals page — one contact
    list, not two."""
    if not payload.contactName.strip():
        raise HTTPException(status_code=400, detail="Contact name is required")
    saved = upsert_entity(
        db,
        "referral",
        {
            "id": new_id("ref_"),
            "contactName": payload.contactName.strip(),
            "companyName": company_name,
            "roleTitle": payload.roleTitle or "",
            "email": payload.email or "",
            "linkedin": payload.linkedin or "",
            "relationship": payload.relationship or "",
            "notes": payload.notes or "",
            "status": "active",
            "source": "networking_manual",
            "createdAt": now_iso(),
        },
    )
    return {"success": True, "contact": saved}


def _profile_snapshot_for_prompt(profile: dict[str, Any]) -> str:
    lines = []
    if profile.get("fullName") or profile.get("name"):
        lines.append(f"Name: {profile.get('fullName') or profile.get('name')}")
    if profile.get("currentTitle"):
        lines.append(f"Current role: {profile.get('currentTitle')}")
    if profile.get("targetRole"):
        lines.append(f"Target role: {profile.get('targetRole')}")
    if profile.get("summary"):
        lines.append(f"Summary: {profile.get('summary')}")
    skills = profile.get("skills")
    if isinstance(skills, list) and skills:
        lines.append(f"Key skills: {', '.join(str(s) for s in skills[:12])}")
    experience = profile.get("experience")
    if isinstance(experience, list) and experience:
        top = experience[0]
        if isinstance(top, dict):
            lines.append(
                f"Most recent role: {top.get('title', '')} at {top.get('company', '')} — "
                f"{top.get('summary') or top.get('description') or ''}".strip()
            )
    return "\n".join(lines) if lines else "No structured profile on file — keep the draft generic but professional."


@router.post("/draft-outreach")
async def draft_outreach(payload: DraftOutreachPayload, db: Session = Depends(db_session)) -> dict[str, Any]:
    """Draft (never send) a personalized outreach email + LinkedIn connection note."""
    profile = get_kv(db, "profile") or {}
    profile_text = _profile_snapshot_for_prompt(profile)

    job_context = ""
    if payload.jobId:
        job = get_discovered_job(db, payload.jobId)
        if job:
            job_context = (
                f"\nTarget role they're applying to: {job.get('title', '')} at {job.get('company', payload.companyName)}\n"
                f"Job description excerpt: {(job.get('description') or '')[:1200]}"
            )

    system_instruction = (
        "You write short, warm, specific networking outreach for a job seeker. "
        "Never invent facts about the sender that aren't given to you. No generic filler "
        'like "I hope this finds you well" or "I came across your profile". Ground every '
        "message in the real background provided. Respond ONLY with a JSON object with keys "
        '"emailSubject" (string), "emailBody" (string, 3-5 sentences), and "linkedinNote" '
        "(string, under 300 characters, no subject line)."
    )
    prompt = (
        f"Sender background:\n{profile_text}\n\n"
        f"Recipient: {payload.contactName}"
        f"{f', {payload.contactRole}' if payload.contactRole else ''} at {payload.companyName}."
        f"{job_context}\n\n"
        "Draft a first-touch outreach email and a LinkedIn connection note asking to connect "
        "and briefly express genuine interest in the team/company, referencing something concrete "
        "from the sender's background above. Do not ask for a referral outright in the LinkedIn note "
        "(too forward for a first connection) — the email may gently mention interest in the role."
    )

    result = await call_openrouter_json(prompt, system_instruction, task="outreach_draft")
    if not result:
        raise HTTPException(
            status_code=503,
            detail="Couldn't generate a draft — OpenRouter isn't configured or the request failed. "
            "Set OPENROUTER_API_KEY in apps/api/.env to enable AI-drafted outreach.",
        )

    return {
        "success": True,
        "draft": {
            "emailSubject": result.get("emailSubject", ""),
            "emailBody": result.get("emailBody", ""),
            "linkedinNote": result.get("linkedinNote", ""),
        },
    }
