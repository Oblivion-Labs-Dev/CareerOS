"""Application outcome recording and archive (ai-job-search outcome.md pattern)."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.services.job_search.methodology import OUTCOME_STATUSES
from app.services.safe_write import atomic_write

ARCHIVE_ROOT = Path(__file__).resolve().parents[3] / "data" / "applications"


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return cleaned or "unknown"


def archive_folder(company: str, role: str) -> Path:
    return ARCHIVE_ROOT / f"{_slug(company)}_{_slug(role)}"


def render_outcome_markdown(
    *,
    company: str,
    role: str,
    status: str,
    notes: str = "",
    interview_stages: list[dict[str, Any]] | None = None,
    date_resolved: str | None = None,
) -> str:
    if status not in OUTCOME_STATUSES:
        raise ValueError(f"Invalid outcome status: {status}")

    lines = [
        f"# Outcome: {company} — {role}",
        "",
        f"**Status:** {status}",
        "",
    ]
    if status != "in_progress" and date_resolved:
        lines.extend([f"**Date resolved:** {date_resolved}", ""])

    lines.extend(["## Interview stages reached", ""])
    stages = interview_stages or []
    if stages:
        for stage in stages:
            mark = "x" if stage.get("completed") else " "
            label = stage.get("label") or stage.get("name") or "Stage"
            date = stage.get("date") or ""
            suffix = f" ({date})" if date else ""
            lines.append(f"- [{mark}] {label}{suffix}")
    else:
        lines.extend(
            [
                "- [ ] Phone screen",
                "- [ ] Technical interview",
                "- [ ] Final round",
                "- [ ] Offer received",
            ]
        )

    lines.extend(["", "## Notes", notes.strip() or "_No notes yet._", ""])
    return "\n".join(lines)


def write_outcome_archive(
    application: dict[str, Any],
    *,
    status: str,
    notes: str = "",
    interview_stages: list[dict[str, Any]] | None = None,
    job_posting: str | None = None,
    cover_letter: str | None = None,
    date_resolved: str | None = None,
) -> dict[str, Any]:
    company = str(application.get("companyName") or application.get("company") or "Unknown")
    role = str(application.get("roleTitle") or application.get("role") or "Unknown role")
    folder = archive_folder(company, role)
    folder.mkdir(parents=True, exist_ok=True)

    outcome_path = folder / "outcome.md"
    outcome_md = render_outcome_markdown(
        company=company,
        role=role,
        status=status,
        notes=notes,
        interview_stages=interview_stages,
        date_resolved=date_resolved,
    )
    atomic_write(outcome_path, outcome_md)

    if job_posting:
        posting_path = folder / "job_posting.md"
        if not posting_path.exists():
            atomic_write(posting_path, job_posting.strip())

    if cover_letter:
        cl_path = folder / "cover_letter.txt"
        if not cl_path.exists():
            atomic_write(cl_path, cover_letter.strip())

    return {
        "archivePath": str(folder),
        "outcomeFile": str(outcome_path),
        "recordedAt": datetime.now(UTC).isoformat(),
    }


def list_outcome_archives() -> list[dict[str, Any]]:
    if not ARCHIVE_ROOT.is_dir():
        return []
    records: list[dict[str, Any]] = []
    for folder in sorted(ARCHIVE_ROOT.iterdir()):
        if not folder.is_dir():
            continue
        outcome_file = folder / "outcome.md"
        if not outcome_file.is_file():
            continue
        text = outcome_file.read_text(encoding="utf-8")
        status_match = re.search(r"\*\*Status:\*\*\s*(\S+)", text)
        records.append(
            {
                "folder": folder.name,
                "path": str(folder),
                "status": status_match.group(1) if status_match else "unknown",
                "outcomePreview": text[:400],
            }
        )
    return records
