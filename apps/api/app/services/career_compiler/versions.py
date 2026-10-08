"""Stage 17-18: immutable resume versions, their DOCX/PDF artifacts, approval and application outcomes.

A version is content-addressed: resume_id is derived from the DOCX bytes, and the PDF stored beside it is the layout
engine's conversion of exactly those bytes. Once approved a version is frozen: nothing here rewrites its files, and
Apply uses the stored PDF without regenerating anything.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.services.career_compiler.docx_render import Rendered, page_fonts, pdf_rows, render_docx
from app.services.career_compiler.docx_template import load_golden, load_spec, template_digest
from app.services.career_compiler.jobs import data_root, load_jd
from app.services.career_compiler.models import JobDescription, ResumeDocument
from app.services.career_compiler.store import CareerStore
from app.services.career_compiler.validator import validate_document

Outcome = Literal["applied", "recruiter_response", "screen", "technical_interview", "onsite", "offer", "rejected", "withdrawn"]
#: Outcomes are recorded, never optimised against: response rates depend on timing, referrals, market, location,
#: company and role level as much as on the resume.
CONFOUNDERS = ("posting age", "referral", "market conditions", "location and visa", "company hiring freeze",
               "role level", "application channel")
_lock = threading.Lock()
CLIP_TOLERANCE = 1.5


class ResumeVersion(BaseModel):
    resume_id: str
    status: Literal["draft", "approved"] = "draft"
    created_at: str
    approved_at: str | None = None
    job_id: str
    job_title: str = ""
    job_company: str = ""
    job_url: str = ""
    jd_hash: str
    career_json_hash: str
    model: str = ""
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    retrieval_version: str = ""
    query_version: str = ""
    template_version: str
    template_sha256: str
    selected_evidence_ids: list[str] = Field(default_factory=list)
    requirement_mappings: dict[str, list[str]] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)
    pdf_checks: dict[str, Any] = Field(default_factory=dict)
    eval_scores: dict[str, Any] = Field(default_factory=dict)
    user_locks: list[str] = Field(default_factory=list)
    docx_sha256: str
    pdf_sha256: str | None = None
    applications: list[dict[str, Any]] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def root() -> Path:
    return data_root() / "resumes"


def _dir(resume_id: str) -> Path:
    if not re.fullmatch(r"rv_[0-9a-f]{16}", resume_id or ""):
        raise ValueError("Unknown resume version id.")
    return root() / resume_id


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def validate_pdf(pdf: bytes, rendered: Rendered, spec: dict[str, Any], *, unmatched: list[str] | None = None) -> dict[str, Any]:
    """The exported PDF itself: one page, selectable text, every section heading and bullet present, nothing
    outside the printable area, and only the template's fonts."""
    import pymupdf
    _, pages, (width, height) = pdf_rows(pdf)
    left, right = spec["margins"]["left"]["pt"] - CLIP_TOLERANCE, width - spec["margins"]["right"]["pt"] + CLIP_TOLERANCE
    clipped: list[str] = []
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        text = "".join(page.get_text() for page in doc)
        for page in doc:
            for block in page.get_text("rawdict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        # Visible glyphs only: trailing spaces and tabs legitimately run into the margin.
                        outside = [c for c in span["chars"] if not c["c"].isspace() and (
                            c["bbox"][0] < left or c["bbox"][2] > right or c["bbox"][1] < -CLIP_TOLERANCE
                            or c["bbox"][3] > height + CLIP_TOLERANCE)]
                        if outside:
                            clipped.append("".join(c["c"] for c in span["chars"])[:60])
    normalized = re.sub(r"[^a-z0-9]", "", text.casefold())
    headings = [b for b in rendered.blocks if b.kind == "heading"]
    missing_headings = [b.key for b in headings if re.sub(r"[^a-z0-9]", "", b.text.casefold()) not in normalized]
    content = [b for b in rendered.blocks if b.kind in ("bullet", "project", "summary")]
    missing = [b.key for b in content if re.sub(r"[^a-z0-9]", "", b.text.casefold()) not in normalized]
    expected_fonts = set(spec["rendered"].get("fonts") or [])
    fonts = sorted(f"{name} {size:g}" for name, size in page_fonts(pdf))
    checks = {"pages": pages, "one_page": pages == 1, "selectable_text": len(normalized) > 200,
              "sections_present": not missing_headings, "missing_sections": missing_headings,
              "no_clipping": not clipped, "clipped": clipped[:5],
              "no_missing_content": not missing and not (unmatched or []), "missing_content": missing + list(unmatched or []),
              "fonts": fonts, "fonts_from_template": not expected_fonts or set(fonts) <= expected_fonts}
    checks["passed"] = all(checks[k] for k in ("one_page", "selectable_text", "sections_present", "no_clipping",
                                               "no_missing_content", "fonts_from_template"))
    return checks


def create_version(document: ResumeDocument, jd: JobDescription, store: CareerStore, *, measurer, meta: dict[str, Any],
                   spec: dict[str, Any] | None = None, golden: bytes | None = None) -> ResumeVersion:
    """Render, convert, check and store one version. Calling it again with the same content returns the stored
    version untouched, and an approved version is never rewritten."""
    spec = spec or load_spec()
    golden = golden or load_golden()
    rendered = render_docx(document, spec, golden, trace=True)
    resume_id = "rv_" + _sha(rendered.docx)[:16]
    folder = _dir(resume_id)
    existing = load_version(resume_id) if (folder / "version.json").is_file() else None
    if existing is not None:
        return existing
    issues = validate_document(document, store)
    measured = measurer.measure(rendered)
    pdf = measured.pdf
    pdf_checks = validate_pdf(pdf, rendered, spec, unmatched=measured.unmatched) if pdf else {
        "passed": False, "reason": f"{measured.engine} produced no PDF; a PDF needs Word or LibreOffice on the API server."}
    items = ([document.summary] if document.summary else []) + document.bullets()
    version = ResumeVersion(
        resume_id=resume_id, created_at=_now(), job_id=jd.id, job_title=jd.title, job_company=jd.company, job_url=jd.url,
        jd_hash=_sha(jd.text.encode()), career_json_hash=store.digest, template_version=template_digest(spec),
        template_sha256=spec["golden"]["sha256"],
        selected_evidence_ids=sorted({i for b in items for i in b.evidence_ids}),
        requirement_mappings={b.id: b.jd_requirement_ids for b in items},
        validation={"valid": not issues and measured.fits, "issues": [i.model_dump() for i in issues],
                    "pages": measured.pages, "engine": measured.engine},
        pdf_checks=pdf_checks, docx_sha256=_sha(rendered.docx), pdf_sha256=_sha(pdf) if pdf else None,
        user_locks=[b.id for b in items if b.locked], **meta)
    with _lock:
        folder.mkdir(parents=True, exist_ok=True)
        _write(folder / "resume.docx", rendered.docx)
        if pdf:
            _write(folder / "resume.pdf", pdf)
        _write(folder / "resume.json", document.model_dump_json(indent=2).encode())
        _write(folder / "version.json", version.model_dump_json(indent=2).encode())
    return version


def load_version(resume_id: str) -> ResumeVersion:
    path = _dir(resume_id) / "version.json"
    if not path.is_file():
        raise FileNotFoundError("That resume version does not exist.")
    return ResumeVersion.model_validate_json(path.read_text(encoding="utf-8"))


def load_document(resume_id: str) -> ResumeDocument:
    return ResumeDocument.model_validate_json((_dir(resume_id) / "resume.json").read_text(encoding="utf-8"))


def blocking_reasons(version: ResumeVersion) -> list[str]:
    reasons = [f"{i['bullet_id']}: {i['message']}" for i in version.validation.get("issues") or []]
    if not version.validation.get("valid") and not reasons:
        reasons.append(f"The resume renders on {version.validation.get('pages')} pages.")
    if not version.pdf_sha256:
        reasons.append(version.pdf_checks.get("reason") or "No PDF was produced.")
    elif not version.pdf_checks.get("passed"):
        failed = [k for k in ("one_page", "selectable_text", "sections_present", "no_clipping", "no_missing_content",
                              "fonts_from_template") if not version.pdf_checks.get(k)]
        reasons.append("PDF checks failed: " + ", ".join(failed))
    return reasons


def artifact(resume_id: str, fmt: Literal["docx", "pdf"]) -> bytes:
    """The stored file, after confirming it is byte-for-byte the one recorded in version.json."""
    version = load_version(resume_id)
    if blocking_reasons(version):
        raise PermissionError("This version failed validation and cannot be downloaded: " + "; ".join(blocking_reasons(version)[:3]))
    expected = version.docx_sha256 if fmt == "docx" else version.pdf_sha256
    data = (_dir(resume_id) / f"resume.{fmt}").read_bytes()
    if _sha(data) != expected:
        raise RuntimeError(f"resume.{fmt} for {resume_id} does not match its recorded hash; refusing to serve it.")
    return data


def _save(version: ResumeVersion) -> None:
    _write(_dir(version.resume_id) / "version.json", version.model_dump_json(indent=2).encode())


def approve(resume_id: str, locks: list[str] | None = None) -> ResumeVersion:
    with _lock:
        version = load_version(resume_id)
        if version.status == "approved":
            return version
        reasons = blocking_reasons(version)
        if reasons:
            raise PermissionError("Cannot approve: " + "; ".join(reasons[:4]))
        version = version.model_copy(update={"status": "approved", "approved_at": _now(),
                                             "user_locks": sorted(set(version.user_locks) | set(locks or []))})
        _save(version)
    return version


def _application_key(application: dict[str, Any]) -> str:
    return str(application.get("autopilot_job_id") or f"manual:{application.get('application_url') or ''}")


def _freeze_jd(version: ResumeVersion) -> None:
    """Keep the structured JD the version was written against beside it: the analysis cache can be refreshed later."""
    path = _dir(version.resume_id) / "jd.json"
    if path.is_file():
        return
    try:
        _write(path, load_jd(version.job_id).model_dump_json(indent=2).encode())
    except (ValueError, FileNotFoundError):
        pass


def frozen_jd(version: ResumeVersion) -> JobDescription | None:
    path = _dir(version.resume_id) / "jd.json"
    if path.is_file():
        return JobDescription.model_validate_json(path.read_text(encoding="utf-8"))
    try:
        return load_jd(version.job_id)
    except (ValueError, FileNotFoundError):
        return None


def link_application(resume_id: str, application: dict[str, Any]) -> ResumeVersion:
    """Record an application made with this version (an autopilot job, or a manual submission). Only metadata
    changes; artifacts never do. One record per autopilot job or per manual application URL."""
    with _lock:
        version = load_version(resume_id)
        if version.status != "approved":
            raise PermissionError("Approve the resume before applying with it.")
        _freeze_jd(version)
        key = _application_key(application)
        if not any(_application_key(a) == key for a in version.applications):
            version = version.model_copy(update={"applications": [*version.applications, {
                **application, "linked_at": _now(), "jd_id": version.job_id, "jd_hash": version.jd_hash,
                "pdf_sha256": version.pdf_sha256, "docx_sha256": version.docx_sha256}]})
            _save(version)
    return version


def record_outcome(resume_id: str, outcome: Outcome, note: str = "", at: str | None = None) -> dict[str, Any]:
    load_version(resume_id)
    item = {"resume_id": resume_id, "outcome": outcome, "note": note[:500], "at": at or _now(), "recorded_at": _now()}
    with _lock, (_dir(resume_id) / "outcomes.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(item) + "\n")
    return item


def record_submission(resume_id: str, autopilot_job_id: str, answers: dict[str, Any] | None = None) -> dict[str, Any] | None:
    """The application agent submitted this version. Recorded once per autopilot job, with the answers it gave."""
    with _lock:
        version = load_version(resume_id)
        changed = False
        applications = []
        for app in version.applications:
            if app.get("autopilot_job_id") == autopilot_job_id and not app.get("submitted_at"):
                app = {**app, "submitted_at": _now(), "answers": dict(answers or {})}
                changed = True
            applications.append(app)
        if changed:
            _save(version.model_copy(update={"applications": applications}))
    note = f"autopilot job {autopilot_job_id}"
    if any(o["outcome"] == "applied" and o.get("note") == note for o in outcomes(resume_id)):
        return None
    return record_outcome(resume_id, "applied", note)


def record_manual_application(resume_id: str, application_url: str, source_job_id: str = "",
                              answers: dict[str, Any] | None = None) -> ResumeVersion:
    """The user submitted this approved version themselves. Idempotent per application URL."""
    version = link_application(resume_id, {"channel": "manual", "application_url": application_url,
                                           "source_job_id": source_job_id, "submitted_at": _now(),
                                           "answers": dict(answers or {})})
    note = f"manual {application_url}"
    if not any(o["outcome"] == "applied" and o.get("note") == note for o in outcomes(resume_id)):
        record_outcome(resume_id, "applied", note)
    return version


def outcomes(resume_id: str) -> list[dict[str, Any]]:
    path = _dir(resume_id) / "outcomes.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def list_versions(job_id: str | None = None) -> list[ResumeVersion]:
    if not root().is_dir():
        return []
    out = []
    for path in sorted(root().glob("rv_*/version.json")):
        version = ResumeVersion.model_validate_json(path.read_text(encoding="utf-8"))
        if job_id is None or version.job_id == job_id:
            out.append(version)
    return sorted(out, key=lambda v: v.created_at, reverse=True)


def frozen_resume_for_job(job_item: dict[str, Any]) -> Path | None:
    """The approved PDF an autopilot job must submit, or None when the job is not bound to a Career OS version.

    Raises when the job is bound but the version is missing, unapproved or its PDF no longer matches its hash, so
    the application agent holds the job instead of silently tailoring a different resume."""
    resume_id = str(job_item.get("careerResumeId") or "")
    if not resume_id:
        return None
    version = load_version(resume_id)
    if version.status != "approved":
        raise PermissionError(f"Career OS resume {resume_id} is not approved.")
    return recruiter_file(resume_id, "pdf")


def recruiter_filename(fmt: Literal["docx", "pdf"], store: CareerStore | None = None) -> str:
    """The name every recruiter-facing copy carries: <First>_<Last>_Resume.<ext>, from career.json."""
    if store is None:
        from app.services.career_compiler.store import load_store
        store = load_store()
    name = re.sub(r"[^A-Za-z0-9]+", "_", str((store.data.get("person") or {}).get("name") or "")).strip("_")
    return f"{name or 'Candidate'}_Resume.{fmt}"


def _recruiter_docx(data: bytes, author: str) -> bytes:
    """The approved DOCX without the internal trace part and with template edit history normalised. Every visible
    part (text, styles, layout) is byte-identical to the approved artifact."""
    import io
    import zipfile
    from app.services.career_compiler.docx_render import TRACE_PART, TRACE_REL_ID
    rels_name = "word/_rels/document.xml.rels"
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as package:
        for info in source.infolist():
            if info.filename == TRACE_PART:
                continue
            body = source.read(info)
            if info.filename == rels_name:
                body = re.sub(rb'<Relationship [^>]*Id="' + TRACE_REL_ID.encode() + rb'"[^>]*/>', b"", body)
            elif info.filename == "docProps/core.xml":
                who = author.encode()
                body = re.sub(rb"<cp:lastModifiedBy>.*?</cp:lastModifiedBy>", b"<cp:lastModifiedBy>" + who + b"</cp:lastModifiedBy>", body)
                body = re.sub(rb"<cp:revision>\d+</cp:revision>", b"<cp:revision>1</cp:revision>", body)
                body = re.sub(rb"<cp:lastPrinted>.*?</cp:lastPrinted>", b"", body)
            elif info.filename == "docProps/app.xml":
                body = re.sub(rb"<TotalTime>\d+</TotalTime>", b"<TotalTime>0</TotalTime>", body)
            package.writestr(info, body)
    return out.getvalue()


def recruiter_artifact(resume_id: str, fmt: Literal["docx", "pdf"]) -> bytes:
    """What leaves Career OS: the hash-verified approved PDF as-is, or the approved DOCX minus internal metadata.
    Deterministic, so downloading or uploading never creates a version."""
    data = artifact(resume_id, fmt)
    if fmt == "pdf":
        return data
    from app.services.career_compiler.store import load_store
    return _recruiter_docx(data, str((load_store().data.get("person") or {}).get("name") or ""))


def recruiter_file(resume_id: str, fmt: Literal["docx", "pdf"]) -> Path:
    """The recruiter-facing copy on disk, named for upload forms (the original artifact stays untouched)."""
    data = recruiter_artifact(resume_id, fmt)
    path = _dir(resume_id) / "recruiter" / recruiter_filename(fmt)
    if not path.is_file() or path.read_bytes() != data:
        path.parent.mkdir(exist_ok=True)
        _write(path, data)
    return path


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")[:40].strip("-")


def version_label(version: ResumeVersion, versions: list[ResumeVersion] | None = None) -> str:
    """company-role-vN: N counts this JD's versions in creation order, so the label never changes."""
    siblings = sorted((v for v in (versions if versions is not None else list_versions(version.job_id))
                       if v.job_id == version.job_id), key=lambda v: v.created_at)
    n = next((i for i, v in enumerate(siblings, 1) if v.resume_id == version.resume_id), len(siblings))
    stem = "-".join(part for part in (_slug(version.job_company), _slug(version.job_title)) if part)
    return f"{stem or 'resume'}-v{n}"


_DESIGN = re.compile(r"\b(design|architect\w*|distributed|scal\w*|system|infrastructure|platform|reliab\w*|latency|throughput)\b", re.I)
_BEHAVIOR = re.compile(r"\b(lead\w*|mentor\w*|collaborat\w*|stakeholder\w*|ownership|own|communicat\w*|cross[- ]functional|influence|conflict|customer\w*)\b", re.I)


def interview_checklist(resume_id: str, store: CareerStore | None = None) -> dict[str, Any]:
    """A prep checklist for the exact resume version submitted, built from stored provenance (no model calls):
    every claim on the page, every JD requirement and the evidence behind it, and the requirements with no
    evidence at all."""
    from app.services.career_compiler.store import load_store
    store = store or load_store()
    version = load_version(resume_id)
    document = load_document(resume_id)
    jd = frozen_jd(version)
    requirements = {r.id: r for r in (jd.requirements if jd else [])}
    bullets = ([document.summary] if document.summary else []) + document.bullets()
    on_page: dict[str, list] = {}
    for b in bullets:
        for rid in version.requirement_mappings.get(b.id, []):
            on_page.setdefault(rid, []).append(b)

    def evidence_lines(ids) -> list[str]:
        return [store.evidence[i].claim for i in ids if i in store.evidence]

    def item(key: str, title: str, detail: str, extra: list[str] | None = None) -> dict[str, Any]:
        return {"id": f"{resume_id}:{key}", "text": title, "detail": detail, **({"examples": extra} if extra else {})}

    claims = [item(f"claim:{b.id}", b.text, "Be ready to explain what you did, how, and the measurable result.",
                   evidence_lines(b.evidence_ids)[:3]) for b in bullets]
    covered, gaps, design, behavioral = [], [], [], []
    for rid, req in requirements.items():
        lines = on_page.get(rid, [])
        text = req.original_text
        if lines:
            entry = item(f"req:{rid}", text, f"{'Required' if req.required else req.importance.title()} · shown in {len(lines)} resume line(s).",
                         [b.text for b in lines[:2]] + evidence_lines([e for b in lines for e in b.evidence_ids])[:2])
            covered.append(entry)
            if _DESIGN.search(text):
                design.append(entry)
            if _BEHAVIOR.search(text):
                behavioral.append(entry)
        else:
            terms = [t for t in (*req.skills, *req.query_terms) if t]
            known = [e.claim for e in store.evidence.values() if e.usable and any(t.lower() in e.claim.lower() for t in terms)]
            if known:
                covered.append(item(f"req:{rid}", text, "Not on the page, but you have evidence. Prepare to bring it up.", known[:2]))
            else:
                gaps.append(item(f"gap:{rid}", text, "No supporting evidence in your career record. Prepare an honest answer: "
                                 "adjacent experience, how you would learn it, or why it is not a blocker."))
    used_projects = {b.project_id for b in bullets if getattr(b, "project_id", "")}
    projects = [item(f"project:{p.id}", p.name, p.summary or "Walk through the problem, your ownership, the design and the result.",
                     list(p.technologies[:6])) for pid, p in store.projects.items() if pid in used_projects]
    if not behavioral:
        behavioral = [item(f"behavior:{e.id}", e.claim, "A STAR story backed by this evidence.")
                      for e in store.evidence.values() if e.usable and _BEHAVIOR.search(e.claim)][:5]
    application = next((a for a in reversed(version.applications) if a.get("submitted_at")), None) or \
        (version.applications[-1] if version.applications else None)
    answers = (application or {}).get("answers") or {}
    sections = [
        {"id": "claims", "title": "Resume claims", "items": claims},
        {"id": "requirements", "title": "JD requirements", "items": covered},
        {"id": "projects", "title": "Projects", "items": projects},
        {"id": "design", "title": "Architecture and system design", "items": design},
        {"id": "behavioral", "title": "Behavioral evidence", "items": behavioral},
        {"id": "gaps", "title": "Genuine gaps", "items": gaps},
        {"id": "answers", "title": "Application answers", "items": [
            item(f"answer:{n}", str(q), str(a)) for n, (q, a) in enumerate(answers.items()) if str(a).strip()]},
    ]
    return {
        "resumeId": resume_id, "label": version_label(version), "company": jd.company if jd else "",
        "title": jd.title if jd else "", "jobUrl": jd.url if jd else "", "jdText": jd.text if jd else "",
        "pdfSha256": version.pdf_sha256, "application": application,
        "sections": [s for s in sections if s["items"]],
    }
