"""Flexible, selectable-text PDF output for evidence-based resumes."""
from __future__ import annotations

from collections import OrderedDict
from html import escape
from io import BytesIO

from app.services.resume_intelligence.local_composer import plain


def document_text(result: dict, profile: dict) -> str:
    if result.get("method") == "minimal-change-v1":
        from app.services.resume_intelligence.baseline_document import render_baseline
        import pymupdf
        with pymupdf.open(stream=render_baseline(result), filetype="pdf") as doc:
            return doc[0].get_text(sort=True)
    lines = [" ".join(str(profile.get(k) or "") for k in ("firstName", "lastName")).strip()]
    lines.append(" | ".join(str(profile.get(k) or "") for k in ("email", "phone", "location") if profile.get(k)))
    lines.append(result.get("targetRoleMatched") or "")
    for heading, bullets in sections(result, profile):
        lines.append(heading)
        lines.extend(bullets)
    return "\n\n".join(line for line in lines if line)


def sections(result: dict, profile: dict) -> list[tuple[str, list[str]]]:
    grouped = OrderedDict()
    for item in result.get("resumeBullets") or []:
        employer = item.get("company") or item.get("project") or "Experience"
        if item.get("evidenceTier") == "personal-project":
            employer = "Personal projects - " + (item.get("project") or employer)
        elif item.get("evidenceTier") != "professional":
            employer = "Evidence classification needed - " + employer
        grouped.setdefault(employer, []).append(item["optimizedBullet"])
    output = []
    experiences = profile.get("workExperience") or []
    for exp in experiences:
        if not isinstance(exp, dict):
            continue
        company = str(exp.get("company") or exp.get("companyName") or "")
        heading = " | ".join(str(v) for v in (company, exp.get("jobTitle") or exp.get("title") or exp.get("role"),
            " - ".join(str(exp.get(k) or "") for k in ("startDate", "endDate")).strip(" -")) if v)
        bullets = grouped.pop(company, [])
        # Keep chronology even for roles with no selected achievements.
        if heading:
            output.append((heading, bullets))
    output.extend(grouped.items())
    education = profile.get("education") or []
    if isinstance(education, list):
        entries = [" | ".join(str(e.get(k) or "") for k in ("school", "institution", "degree", "fieldOfStudy", "graduationDate") if e.get(k)) for e in education if isinstance(e, dict)]
        if any(entries):
            output.append(("Education", [e for e in entries if e]))
    if result.get("skillsList"):
        output.append(("Skills evidenced in this resume", [", ".join(result["skillsList"])]))
    return output


def render(result: dict, profile: dict, *, draft: bool = False) -> bytes:
    if result.get("method") == "minimal-change-v1":
        from app.services.resume_intelligence.baseline_document import render_baseline
        if not draft and not result.get("exportReady"):
            raise ValueError("Review evidence warnings before exporting this resume.")
        return render_baseline(result)
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.colors import HexColor
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, KeepTogether
    from reportlab.lib.pagesizes import letter

    if not draft and not result.get("exportReady"):
        raise ValueError("Review evidence warnings before exporting this resume.")
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=42, leftMargin=42, topMargin=36, bottomMargin=36)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=10, leading=13, spaceAfter=5)
    heading = ParagraphStyle("heading", parent=body, fontName="Helvetica-Bold", fontSize=11, spaceBefore=10, textColor=HexColor("#24364b"))
    name = ParagraphStyle("name", parent=heading, fontSize=20, leading=24, spaceBefore=0)
    def p(text, style=body):
        return Paragraph(escape(plain(text)), style)
    flow = []
    if draft:
        flow.append(p("DRAFT - source claims require review", heading))
    flow.append(p(" ".join(str(profile.get(k) or "") for k in ("firstName", "lastName")).strip(), name))
    flow.append(p(" | ".join(str(profile.get(k) or "") for k in ("email", "phone", "location", "linkedIn", "github") if profile.get(k))))
    if result.get("targetRoleMatched"):
        flow.append(p(result["targetRoleMatched"], heading))
    for title, bullets in sections(result, profile):
        first = [p(title, heading)]
        if bullets:
            first.append(p(bullets[0]))
        flow.append(KeepTogether(first))
        flow.extend(p(bullet) for bullet in bullets[1:])
    flow.append(Spacer(1, 2))
    doc.build(flow)
    from pypdf import PdfReader
    if len(PdfReader(BytesIO(buffer.getvalue())).pages) > int(result.get("maxPages") or 1):
        raise ValueError("The resume exceeds the selected page limit. Choose more pages or fewer accomplishments.")
    return buffer.getvalue()
