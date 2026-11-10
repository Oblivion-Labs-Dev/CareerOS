"""The recruiter CSV generator must read both the old export layout and the
"HIRING MANAGERS" layout (Title-case headers, "Work Email", BOM)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "email" / "generate_csv_recruiter_emails.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("generate_csv_recruiter_emails", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_hiring_managers_layout_with_bom(tmp_path: Path) -> None:
    gen = _load_module()
    csv_path = tmp_path / "hm.csv"
    csv_path.write_text(
        "﻿First Name,Last Name,Full Name,Job Title,Company,Work Email,Email Status,LinkedIn URL\n"
        "Neha,Gupta,Neha Gupta,Lead TA Partner,BlackLine,neha.gupta1@blackline.com,Found online,https://li/neha\n"
        "Sam,Lee,Sam Lee,CTO,Acme,,Not built,https://li/sam\n"
        "Neha,Gupta,Neha Gupta,Lead TA Partner,BlackLine,NEHA.GUPTA1@blackline.com,Found online,https://li/neha\n",
        encoding="utf-8",
    )

    entries = gen.build_personalized(gen.load_csv_rows(csv_path), {})

    assert len(entries) == 1
    entry = entries[0]
    assert entry["email"] == "neha.gupta1@blackline.com"
    assert entry["firstName"] == "Neha"
    assert entry["recruiterName"] == "Neha Gupta"
    assert entry["title"] == "Lead TA Partner"
    assert entry["linkedin"] == "https://li/neha"
    assert entry["emailStatus"] == "Found online"
    assert entry["body"].startswith("Hi Neha,")


def test_original_layout_still_parses(tmp_path: Path) -> None:
    gen = _load_module()
    csv_path = tmp_path / "old.csv"
    csv_path.write_text(
        "junk preamble\n"
        "First name,Last name,Title,Company,Email,Linkedin\n"
        "Ana,Diaz,Recruiter,Stripe,ana@stripe.com,https://li/ana\n",
        encoding="utf-8",
    )

    entries = gen.build_personalized(gen.load_csv_rows(csv_path), {})

    assert [e["email"] for e in entries] == ["ana@stripe.com"]
    assert entries[0]["title"] == "Recruiter"
    assert entries[0]["linkedin"] == "https://li/ana"
