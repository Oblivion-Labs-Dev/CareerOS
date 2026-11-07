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


_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_UNREADABLE = "Could not extract text from resume"


def _docx_part_text(xml_content: bytes) -> list[str]:
    paragraphs = []
    for p in ET.fromstring(xml_content).iter(f"{_W}p"):
        pieces: list[str] = []
        for node in p.iter():
            if node.tag == f"{_W}t" and node.text:
                pieces.append(node.text)
            elif node.tag == f"{_W}tab":
                pieces.append("\t")
            elif node.tag in (f"{_W}br", f"{_W}cr"):
                pieces.append("\n")
        line = "".join(pieces)
        if line.strip():
            paragraphs.append(line)
    return paragraphs


def extract_docx_text(raw_bytes: bytes) -> str:
    """Readable text from a Word DOCX package, without external dependencies.

    Headers come first because many templates put the name and contact details
    there; tabs and line breaks are kept because templates align dates with
    them, and dropping them glues the title onto the dates.
    """
    try:
        with zipfile.ZipFile(io.BytesIO(raw_bytes)) as z:
            names = z.namelist()
            headers = sorted(n for n in names if re.fullmatch(r"word/header\d*\.xml", n))
            footers = sorted(n for n in names if re.fullmatch(r"word/footer\d*\.xml", n))
            paragraphs: list[str] = []
            for part in [*headers, "word/document.xml", *footers]:
                paragraphs.extend(_docx_part_text(z.read(part)))
            return "\n".join(paragraphs)
    except Exception:
        return ""


def _rtf_to_text(raw: str) -> str:
    """Plain text from an RTF document: enough for a resume, no layout."""
    out: list[str] = []
    skip_depth: list[int] = []
    depth = 0
    i = 0
    destinations = {"fonttbl", "colortbl", "stylesheet", "info", "pict", "header", "footer",
                    "listtable", "listoverridetable", "rsidtbl", "generator", "themedata",
                    "colorschememapping", "datastore", "latentstyles"}
    pending_skip = 0
    while i < len(raw):
        ch = raw[i]
        skipping = bool(skip_depth) and depth >= skip_depth[-1]
        if ch == "{":
            depth += 1
            i += 1
            if raw.startswith("\\*", i):
                skip_depth.append(depth)
            continue
        if ch == "}":
            if skip_depth and depth == skip_depth[-1]:
                skip_depth.pop()
            depth -= 1
            i += 1
            continue
        if ch == "\\":
            m = re.match(r"\\([a-zA-Z]+)(-?\d+)? ?|\\'([0-9a-fA-F]{2})|\\(.)", raw[i:])
            if not m:
                i += 1
                continue
            i += m.end()
            word, arg, hexcode, symbol = m.groups()
            if skipping:
                continue
            if word:
                if word in destinations:
                    skip_depth.append(depth)
                elif word in ("par", "line", "row", "sect", "page"):
                    out.append("\n")
                elif word in ("tab", "cell"):
                    out.append("\t")
                elif word == "u" and arg:
                    code = int(arg)
                    out.append(chr(code + 65536 if code < 0 else code))
                    pending_skip = 1
            elif hexcode:
                if pending_skip:
                    pending_skip -= 1
                else:
                    out.append(bytes([int(hexcode, 16)]).decode("cp1252", errors="replace"))
            elif symbol in ("\\", "{", "}"):
                out.append(symbol)
            elif symbol == "~":
                out.append(" ")
            continue
        if ch in "\r\n":
            i += 1
            continue
        if not skipping:
            if pending_skip:
                pending_skip -= 1
            else:
                out.append(ch)
        i += 1
    return "".join(out)


def _decode_text(raw: bytes) -> str:
    """Plain text in whichever encoding the file declares, or a clear refusal."""
    if raw.startswith(b"\xef\xbb\xbf"):
        text = raw[3:].decode("utf-8", errors="replace")
    elif raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        text = raw.decode("utf-16", errors="replace")
    else:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252", errors="replace")
    sample = text[:4000]
    control = sum(1 for c in sample if (ord(c) < 32 and c not in "\t\r\n\f") or c == "\ufffd")
    if sample and control / len(sample) > 0.05:
        raise ValueError(
            f"{_UNREADABLE}: this file is not a format CareerOS can read. Upload a PDF, DOCX, RTF or TXT file."
        )
    return text


def _normalise_text(text: str) -> str:
    """Typographic look-alikes as plain characters.

    PDF and Word exports often write spaces as no-break spaces and hyphens as
    soft or non-breaking hyphens; left alone they break every phone number and
    date range ("Jan 2021­ Present") the parser looks for. A soft
    hyphen inside a word is only a line-break hint, so it is dropped there.
    """
    text = re.sub(r"[  -   　]", " ", text)
    text = re.sub(r"[​‌‍⁠﻿]", "", text)
    text = re.sub(r"[‐‑‒−]", "-", text)
    text = re.sub(r"(?<=[\d\s])­|­(?=[\d\s])", "-", text)
    return text.replace("­", "")


def read_resume_text(attachment: dict[str, Any] | None) -> str:
    """Text of an uploaded resume, normalised, or a ValueError saying why not."""
    return _normalise_text(_read_resume_text(attachment))


def _read_resume_text(attachment: dict[str, Any] | None) -> str:
    """Text of an uploaded resume, or a ValueError saying why it can't be read.

    PDFs go through PyMuPDF (good with multi-column layouts) with pypdf as a
    fallback; Word .docx is read natively; RTF and plain text are decoded. A file
    that cannot be read is refused rather than decoded into garbage, because
    that garbage would otherwise be written into the profile.
    """
    if not attachment or not attachment.get("base64"):
        raise ValueError(f"{_UNREADABLE}: no file content")
    try:
        raw = base64.b64decode(attachment["base64"], validate=True)
    except Exception:
        raise ValueError(f"{_UNREADABLE}: the upload is not valid base64") from None

    name = str(attachment.get("name") or "").lower()
    mime = str(attachment.get("type") or attachment.get("mimeType") or "").lower()

    if raw.startswith(_OLE_MAGIC) or name.endswith(".doc") or mime == "application/msword":
        raise ValueError(
            f"{_UNREADABLE}: old Word .doc files can't be read. Save it as DOCX or PDF and upload again."
        )

    if name.endswith(".docx") or "officedocument" in mime or raw.startswith(b"PK\x03\x04"):
        text = extract_docx_text(raw)
        if not text.strip():
            raise ValueError(f"{_UNREADABLE}: the Word file is damaged or empty. Save it again as DOCX or PDF.")
        return text

    if "pdf" in mime or name.endswith(".pdf") or raw.startswith(b"%PDF"):
        try:
            import pymupdf

            doc = pymupdf.open(stream=raw, filetype="pdf")
            extracted = "\n".join(page.get_text("text") or "" for page in doc)
            if extracted.strip():
                return extracted
        except Exception:
            pass
        try:
            reader = PdfReader(io.BytesIO(raw))
            extracted = "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception:
            extracted = ""
        if not extracted.strip():
            raise ValueError(
                f"{_UNREADABLE}: the PDF has no readable text (it may be a scan). Export it with text, or upload DOCX."
            )
        return extracted

    if name.endswith(".rtf") or "rtf" in mime or raw.lstrip().startswith(b"{\\rtf"):
        try:
            rtf = raw.decode("utf-8")
        except UnicodeDecodeError:
            rtf = raw.decode("cp1252", errors="replace")
        text = _rtf_to_text(rtf)
        if not text.strip():
            raise ValueError(f"{_UNREADABLE}: the RTF file is empty.")
        return text

    text = _decode_text(raw)
    if not text.strip():
        raise ValueError(f"{_UNREADABLE}: the file is empty.")
    return text


def extract_text_from_attachment(attachment: dict[str, Any] | None) -> str:
    """Text of an attachment, or "" when it can't be read (see read_resume_text)."""
    try:
        return read_resume_text(attachment)
    except ValueError:
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


def _name_line(lines: list[str]) -> str:
    """The first header line that reads like a person's name, or "".

    A heading ("SUMMARY") or a contact line is never a name; when nothing fits,
    the name stays unknown for the user to fill in instead of being guessed.
    """
    from app.services.resume_structure import _SECTION_PATTERNS

    for line in lines:
        if any(pattern.match(line) for pattern in _SECTION_PATTERNS.values()):
            continue
        if EMAIL_RE.search(line) or re.search(r"\d|https?://|www\.|[|@]", line):
            continue
        words = line.split()
        if 1 <= len(words) <= 5 and all(re.fullmatch(r"[^\W\d_][\w.'’-]*,?", w) for w in words):
            return line
    return ""


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
    name_line = _name_line(lines[:8])
    if name_line and not updated.get("fullName"):
        updated["fullName"] = name_line
        parts = name_line.split()
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

    text = read_resume_text(resume)

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

    text = read_resume_text(resume)

    updated, extracted = parse_resume_fields(text, profile)
    return {
        "profile": updated,
        "extracted": extracted,
        "textPreview": text[:1200],
    }
