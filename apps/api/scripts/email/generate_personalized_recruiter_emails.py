#!/usr/bin/env python3
"""Generate recruiter-personalized outreach emails from a .docx template source."""

from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[5]
DEFAULT_DOCX = Path(r"C:\Users\amsbo\Downloads\company_outreach_emails_humanized.docx")
DEFAULT_RECRUITERS = ROOT / "Arsenal" / "scripts" / "email" / "recruiters.json"
DEFAULT_OUTPUT = ROOT / "CareerOS" / "apps" / "api" / "scripts" / "email" / "personalized_recruiter_emails.json"

WORD_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}

COMPANY_ALIASES = {
    "docusign": "docusign",
    "docusing": "docusign",
    "doordash": "doordash",
    "sofi": "sofi",
}


def normalize_company(name: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "", name.lower())
    return COMPANY_ALIASES.get(cleaned, cleaned)


def extract_first_name(full_name: str) -> str:
    parts = [part for part in full_name.strip().split() if part]
    return parts[0] if parts else ""


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
    body = body.replace("�", "\n• ")
    body = body.replace("15�20", "15-20")
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
    body = body.replace("\n\nGitHub:", "\nGitHub:")
    body = body.replace("\n\nResume:", "\nResume:")
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body.strip()


def parse_company_templates(docx_path: Path) -> dict[str, dict[str, str]]:
    paragraphs = read_docx_paragraphs(docx_path)
    try:
        start = paragraphs.index("Company Outreach Emails") + 1
    except ValueError as exc:
        raise RuntimeError("Could not find 'Company Outreach Emails' section in the .docx file.") from exc

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


def generate_personalized_emails(
    recruiter_path: Path,
    template_map: dict[str, dict[str, str]],
) -> tuple[list[dict[str, str]], list[str]]:
    recruiter_data = json.loads(recruiter_path.read_text(encoding="utf-8"))
    personalized: list[dict[str, str]] = []
    missing_companies: list[str] = []

    for company_entry in recruiter_data:
        company = company_entry["company"]
        template = template_map.get(normalize_company(company))
        if not template:
            missing_companies.append(company)
            continue
        for recruiter in company_entry["recruiters"]:
            first_name = extract_first_name(recruiter["name"])
            body = template["bodyTemplate"].replace("{{FirstName}}", first_name or recruiter["name"])
            personalized.append(
                {
                    "company": company,
                    "recruiterName": recruiter["name"],
                    "firstName": first_name,
                    "email": recruiter["email"],
                    "subject": template["subject"],
                    "body": body,
                }
            )
    return personalized, missing_companies


def main() -> int:
    docx_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DOCX
    recruiter_path = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_RECRUITERS
    output_path = Path(sys.argv[3]) if len(sys.argv) > 3 else DEFAULT_OUTPUT

    if not docx_path.exists():
        print(f"Missing .docx file: {docx_path}")
        return 1
    if not recruiter_path.exists():
        print(f"Missing recruiter list: {recruiter_path}")
        return 1

    templates = parse_company_templates(docx_path)
    personalized, missing_companies = generate_personalized_emails(recruiter_path, templates)

    output_path.write_text(json.dumps(personalized, indent=2), encoding="utf-8")

    print(f"Wrote {len(personalized)} personalized emails to {output_path}")
    if missing_companies:
        print("Missing company templates:")
        for company in missing_companies:
            print(f"- {company}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
