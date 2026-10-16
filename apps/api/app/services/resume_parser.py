import base64
import io
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Any

from pypdf import PdfReader

from app.services.profile_normalizer import normalize_work_authorization

EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE_RE = re.compile(r"(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b")
YEARS_RE = re.compile(r"(\d{1,2})\+?\s*years?\s+(?:of\s+)?experience", re.I)


def extract_docx_text(raw_bytes: bytes) -> str:
    """Extract readable text from a Word DOCX package without external dependencies."""
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
            xml_content = z.read("word/document.xml")
            tree = ET.fromstring(xml_content)
            paragraphs = []
            for p in tree.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
                texts = [
                    node.text
                    for node in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")
                    if node.text
                ]
                if texts:
                    paragraphs.append("".join(texts))
            return "\n".join(paragraphs)
    except Exception:
        return ""


def extract_text_from_attachment(attachment: dict[str, Any] | None) -> str:
    """Extract clean text from PDF, DOCX, or plain text attachments.

    Uses PyMuPDF (fitz) for high-fidelity multi-column layout parsing when available,
    falling back to pypdf, and native XML parsing for Word .docx files.
    """
    if not attachment or not attachment.get("base64"):
        return ""
    try:
        raw = base64.b64decode(attachment["base64"], validate=True)
    except Exception:
        return ""

    name = str(attachment.get("name") or "").lower()
    mime = str(attachment.get("type") or attachment.get("mimeType") or "").lower()

    # 1. Word DOCX documents
    if name.endswith(".docx") or "word" in mime or "officedocument" in mime:
        text = extract_docx_text(raw)
        if text.strip():
            return text

    # 2. PDF documents
    if "pdf" in mime or name.endswith(".pdf"):
        # Try PyMuPDF first for superior multi-column layout handling
        try:
            import pymupdf

            doc = pymupdf.open(stream=raw, filetype="pdf")
            extracted = "\n".join(page.get_text("text") or "" for page in doc)
            if extracted.strip():
                return extracted
        except Exception:
            pass

        # Fallback to pypdf
        try:
            reader = PdfReader(io.BytesIO(raw))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            return ""

    # 3. Plain text / markdown fallback
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return ""


async def parse_resume_with_llm(text: str) -> dict[str, Any] | None:
    """Extract structured candidate information from resume text using LLM."""
    from app.services.llm import call_openrouter_json

    system_instruction = (
        "You are an expert resume parsing engine. Given the plain text of a candidate's resume, "
        "extract clean, accurate, and structured profile facts. Return ONLY a valid JSON object "
        "matching the requested schema. Never invent dates, companies, or facts not in the text."
    )

    prompt = f"""Extract the candidate's profile into this JSON schema:
{{
  "fullName": "Candidate full name",
  "firstName": "First name",
  "lastName": "Last name",
  "email": "Email address",
  "phone": "Phone number",
  "city": "City",
  "state": "State or region",
  "country": "Country",
  "zip": "Postal code",
  "currentTitle": "Most recent or current job title",
  "currentCompany": "Most recent or current company name",
  "targetRole": "Primary target role or current specialization",
  "yearsExperience": 5,
  "linkedin": "LinkedIn profile URL if mentioned",
  "github": "GitHub profile URL if mentioned",
  "website": "Personal website or portfolio URL if mentioned",
  "skills": ["Skill1", "Skill2"],
  "workExperience": [
    {{
      "company": "Company Name",
      "jobTitle": "Job Title",
      "location": "Location",
      "startDate": "MM/YYYY or YYYY",
      "endDate": "MM/YYYY or Present",
      "currentlyEmployed": true,
      "bullets": ["Achievement 1", "Achievement 2"]
    }}
  ],
  "education": [
    {{
      "school": "Institution Name",
      "degree": "Degree (e.g. Bachelor of Science)",
      "discipline": "Major / Field of Study",
      "startYear": "YYYY",
      "endYear": "YYYY",
      "gpa": "GPA if mentioned"
    }}
  ]
}}

Resume text:
\"\"\"
{text[:12000]}
\"\"\"
"""
    try:
        res = await call_openrouter_json(prompt, system_instruction, task="resume_parsing")
        return res if isinstance(res, dict) else None
    except Exception:
        return None


def parse_resume_fields(
    text: str,
    profile: dict[str, Any],
    llm_data: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    extracted: dict[str, Any] = {}
    updated = dict(profile)

    # 1. Ingest LLM extracted structured data if available
    if llm_data and isinstance(llm_data, dict):
        for k, v in llm_data.items():
            if v and v not in ("null", "None", ""):
                extracted[k] = v
                if not updated.get(k):
                    updated[k] = v

    # 2. Regex fallback / guarantee for core contact facts
    email = EMAIL_RE.search(text)
    if email and not updated.get("email"):
        updated["email"] = email.group(0)
        extracted["email"] = updated["email"]

    phone = PHONE_RE.search(text)
    if phone and not updated.get("phone"):
        updated["phone"] = phone.group(0)
        extracted["phone"] = updated["phone"]

    years = YEARS_RE.search(text)
    if years and not updated.get("yearsExperience"):
        try:
            updated["yearsExperience"] = int(years.group(1))
        except Exception:
            updated["yearsExperience"] = years.group(1)
        extracted["yearsExperience"] = updated["yearsExperience"]

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if lines and not updated.get("fullName"):
        updated["fullName"] = lines[0]
        parts = lines[0].split()
        if len(parts) >= 2:
            updated["firstName"] = parts[0]
            updated["lastName"] = " ".join(parts[1:])
        extracted["fullName"] = updated["fullName"]

    # Extract location from the header lines if missing
    if not updated.get("location"):
        header_text = " | ".join(lines[:6])
        loc_match = re.search(r"\b([A-Z][a-zA-Z\s]{1,25}),\s*([A-Z]{2})\b", header_text)
        if loc_match:
            city = loc_match.group(1).strip()
            state = loc_match.group(2).strip()
            updated["city"] = city
            updated["state"] = state
            updated["location"] = f"{city}, {state}"
            extracted["city"] = city
            extracted["state"] = state
            extracted["location"] = updated["location"]

    # 3. Deterministic structure fallback (experience, education, skills)
    from app.services.resume_structure import parse_structure

    for key, value in parse_structure(text).items():
        if not value:
            continue
        if key not in extracted or not extracted[key]:
            extracted[key] = value
        if not updated.get(key):
            updated[key] = value

    # Infer current title/company and target role from first work experience if unset
    if updated.get("workExperience") and isinstance(updated["workExperience"], list) and updated["workExperience"]:
        first_role = updated["workExperience"][0]
        if not updated.get("currentCompany") and first_role.get("company"):
            updated["currentCompany"] = first_role["company"]
            extracted["currentCompany"] = updated["currentCompany"]
        first_title = first_role.get("jobTitle") or first_role.get("title")
        if not updated.get("currentTitle") and first_title:
            updated["currentTitle"] = first_title
            extracted["currentTitle"] = updated["currentTitle"]
        if not updated.get("targetRole") and first_title:
            updated["targetRole"] = first_title
            extracted["targetRole"] = updated["targetRole"]

    # 4. Normalize work authorization flags
    updated = normalize_work_authorization(updated)
    return updated, extracted


async def parse_resume_into_profile_async(
    profile: dict[str, Any],
    documents: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Asynchronous resume parsing supporting LLM-guided structured extraction."""
    resume = documents.get("defaultResume")
    if not resume:
        raise ValueError("No default resume uploaded")

    needs_parse = force or not profile.get("email") or not profile.get("phone")
    if not needs_parse:
        return {"profile": profile, "extracted": {}, "textPreview": ""}

    text = extract_text_from_attachment(resume)
    if not text.strip():
        raise ValueError("Could not extract text from resume")

    # Attempt structured LLM extraction
    llm_data = await parse_resume_with_llm(text)
    updated, extracted = parse_resume_fields(text, profile, llm_data=llm_data)

    return {
        "profile": updated,
        "extracted": extracted,
        "textPreview": text[:1200],
    }


def parse_resume_into_profile(
    profile: dict[str, Any],
    documents: dict[str, Any],
    *,
    force: bool = False,
) -> dict[str, Any]:
    """Synchronous entry point for parsing resume into profile."""
    resume = documents.get("defaultResume")
    if not resume:
        raise ValueError("No default resume uploaded")

    needs_parse = force or not profile.get("email") or not profile.get("phone")
    if not needs_parse:
        return {"profile": profile, "extracted": {}, "textPreview": ""}

    text = extract_text_from_attachment(resume)
    if not text.strip():
        raise ValueError("Could not extract text from resume")

    updated, extracted = parse_resume_fields(text, profile)
    return {
        "profile": updated,
        "extracted": extracted,
        "textPreview": text[:1200],
    }
