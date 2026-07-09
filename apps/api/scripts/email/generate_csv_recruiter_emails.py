#!/usr/bin/env python3
"""Generate personalized outreach emails from a recruiter CSV export."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[5]
DEFAULT_CSV = Path(r"C:\Users\amsbo\Downloads\Copy of List of Recruiters.xlsx - Sheet1.csv")
DEFAULT_DOCX = Path(r"C:\Users\amsbo\Downloads\company_outreach_emails_humanized.docx")
DEFAULT_GENERIC = (
    Path(__file__).resolve().parent / "recruiter_outreach_template.json"
)
DEFAULT_OUTPUT = Path(__file__).resolve().parent / "personalized_csv_recruiter_emails.json"

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

COMPANY_ALIASES = {
    "docusign": "docusign",
    "doordash": "doordash",
    "sofi": "sofi",
    "cashapp": "cashapp",
    "electronicartsea": "ea",
}


def normalize_company(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", name.lower())
    return COMPANY_ALIASES.get(cleaned, cleaned)


def read_docx_paragraphs(path: Path) -> list[str]:
    with ZipFile(path) as archive:
        xml = archive.read("word/document.xml")
    root = ET.fromstring(xml)
    paragraphs: list[str] = []
    for para in root.findall(".//w:p", WORD_NS):
        text = "".join(node.text or "" for node in para.findall(".//w:t", WORD_NS)).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def cleanup_email_body(raw_body: str) -> str:
    body = raw_body.replace("{FirstName}", "{{FirstName}}")
    body = body.replace("•", "\n• ")
    body = body.replace("\ufffd", "\n• ")
    body = body.replace("1520", "15-20")
    body = re.sub(r"(?<!\n)(Hi \{\{FirstName\}\},)", r"\1\n\n", body)
    body = re.sub(r"(?<!\n)(I hope you're doing well\.)", r"\1\n\n", body, count=1)
    body = re.sub(r"(?<!\n)(I'm reaching out because)", r"\n\1", body, count=1)
    body = re.sub(r"(?<!\n)(I'm currently a Senior Software Engineer)", r"\n\1", body, count=1)
    body = re.sub(r"(?<!\n)(A few examples of the work I've done:)", r"\n\1\n", body, count=1)
    body = re.sub(r"(?<!\n)(One of the reasons I'm interested in )", r"\n\1", body, count=1)
    body = re.sub(r"(?<!\n)(If you think my background could be a fit)", r"\n\1", body, count=1)
    body = re.sub(r"(?<!\n)(Thanks for taking the time to read this\.)", r"\n\1", body, count=1)
    body = re.sub(r"(?<!\n)(Best,)", r"\n\1", body, count=1)
    body = body.replace("Best,Akshay Borse", "Best,\n\nAkshay Borse")
    body = body.replace("Akshay BorseLinkedIn:", "Akshay Borse\n\nLinkedIn:")
    body = body.replace("GitHub:", "\nGitHub:")
    body = body.replace("Resume:", "\nResume:")
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def parse_company_templates(docx_path: Path) -> dict[str, dict[str, str]]:
    paragraphs = read_docx_paragraphs(docx_path)
    start = paragraphs.index("Company Outreach Emails") + 1
    templates: dict[str, dict[str, str]] = {}
    index = start
    while index + 2 < len(paragraphs):
        company = paragraphs[index].strip()
        if company.startswith("SESSION RECAP"):
            break
        subject_line = paragraphs[index + 1].strip()
        body_line = paragraphs[index + 2].strip()
        if not subject_line.startswith("Subject: "):
            index += 1
            continue
        templates[normalize_company(company)] = {
            "company": company,
            "subject": subject_line.removeprefix("Subject: ").strip(),
            "bodyTemplate": cleanup_email_body(body_line),
        }
        index += 3
    return templates


def load_csv_rows(csv_path: Path) -> list[dict[str, str]]:
    with csv_path.open(encoding="utf-8", errors="ignore", newline="") as handle:
        rows = list(csv.reader(handle))
    header_idx = next(i for i, row in enumerate(rows) if row and row[0].strip() == "First name")
    header = rows[header_idx]
    parsed: list[dict[str, str]] = []
    for raw in rows[header_idx + 1 :]:
        if not any(cell.strip() for cell in raw):
            continue
        if len(raw) < len(header):
            raw = raw + [""] * (len(header) - len(raw))
        elif len(raw) > len(header):
            raw = raw[: len(header)]
        parsed.append({header[i]: raw[i] for i in range(len(header))})
    return parsed


def recruiter_name(row: dict[str, str]) -> str:
    first = (row.get("First name") or "").strip()
    last = (row.get("Last name") or "").strip()
    return " ".join(part for part in (first, last) if part).strip() or "there"


def fallback_template(company: str) -> dict[str, str]:
    display_company = company or "your company"
    return {
        "subject": f"Senior Software Engineer at Microsoft | Interested in Opportunities at {display_company}",
        "bodyTemplate": (
            "Hi {{FirstName}},\n\n"
            "I hope you're doing well.\n\n"
            f"I'm reaching out because I'm starting to look at new opportunities, and {display_company} is one of the companies I wanted to reach out to.\n\n"
            "I'm currently a Senior Software Engineer at Microsoft. Before that I spent close to six years at Amazon. "
            "Most of my work has been around backend systems, distributed services, cloud infrastructure, and building internal platforms that help engineers move faster.\n\n"
            "A few examples of the work I've done:\n\n"
            "• Built enterprise security capabilities protecting more than 237K AI agents across 13K+ tenants.\n"
            "• Designed distributed systems handling over 100K transactions per second.\n"
            "• Built internal tooling that reduced service setup from weeks to hours.\n"
            "• Led infrastructure improvements that reduced operational costs by more than $250K per month.\n\n"
            f"One of the reasons I'm interested in {display_company} is the opportunity to work on large-scale engineering systems. "
            "That's the kind of engineering work I enjoy and where I think my experience would translate well.\n\n"
            "If you think my background could be a fit for any of your teams, I'd really appreciate the chance to talk. "
            "Even a quick 15-20 minute conversation would be great.\n\n"
            "Thanks for taking the time to read this. I've attached my resume and included a few links below if you'd like to learn a little more about my background.\n\n"
            "Best,\n\n"
            "Akshay Borse\n\n"
            "LinkedIn: https://www.linkedin.com/in/amsborse/\n"
            "GitHub: https://github.com/amsborse\n"
            "Resume: https://amsborse.github.io/resume"
        ),
    }


def build_personalized(rows: list[dict[str, str]], template_map: dict[str, dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    personalized: list[dict[str, str]] = []
    for row in rows:
        email = (row.get("Email") or "").strip()
        if not email or not EMAIL_RE.match(email):
            continue
        key = email.lower()
        if key in seen:
            continue
        seen.add(key)

        company = (row.get("Company") or "").strip() or "Unknown company"
        first_name = (row.get("First name") or "").strip() or recruiter_name(row).split()[0]
        template = template_map.get(normalize_company(company)) or fallback_template(company)
        body = template["bodyTemplate"].replace("{{FirstName}}", first_name or "there")

        personalized.append(
            {
                "company": company,
                "recruiterName": recruiter_name(row),
                "firstName": first_name,
                "email": email,
                "title": (row.get("Title") or "").strip(),
                "linkedin": (row.get("Linkedin") or "").strip(),
                "subject": template["subject"],
                "body": body,
            }
        )
    return personalized


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate personalized emails from recruiter CSV")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV)
    parser.add_argument("--docx", type=Path, default=DEFAULT_DOCX)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if not args.csv.exists():
        print(f"Missing CSV: {args.csv}")
        return 1

    template_map = parse_company_templates(args.docx) if args.docx.exists() else {}
    rows = load_csv_rows(args.csv)
    personalized = build_personalized(rows, template_map)
    args.output.write_text(json.dumps(personalized, indent=2), encoding="utf-8")

    print(f"Wrote {len(personalized)} unique recruiter emails to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
