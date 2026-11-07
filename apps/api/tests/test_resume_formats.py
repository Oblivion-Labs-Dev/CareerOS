"""Resumes arrive as PDF, Word, RTF and plain text, laid out many ways.

Without an AI key the deterministic parser is the only one that runs, so each
format must either be read correctly or refused with a clear reason. Reading a
file as garbage and writing that into the profile is the one outcome that must
never happen. All resume content here is fictional.
"""

import base64
import io
import zipfile

import pytest

from app.services.resume_parser import (
    extract_text_from_attachment,
    parse_resume_fields,
    parse_resume_into_profile,
    read_resume_text,
)
from app.services.resume_structure import parse_experience, parse_education

PM_LINES = [
    "Jordan Lee",
    "Austin, TX | jordan.lee@example.com | (512) 555-0199",
    "SUMMARY",
    "Product manager with 7 years of experience shipping B2B SaaS.",
    "EXPERIENCE",
    "Senior Product Manager, Acme Cloud — Austin, TX",
    "Jan 2021 - Present",
    "- Owned the billing roadmap.",
    "Product Manager, Brightline Analytics — Remote",
    "Jun 2017 - Dec 2020",
    "EDUCATION",
    "University of Texas at Austin — B.S. Computer Science, 2017",
    "SKILLS",
    "Roadmapping, SQL, A/B testing, Figma",
]
PM_TEXT = "\n".join(PM_LINES) + "\n"

W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _para(line: str) -> str:
    segments = line.split("\t")
    runs = "<w:r><w:tab/></w:r>".join(
        f'<w:r><w:t xml:space="preserve">{segment}</w:t></w:r>' for segment in segments
    )
    return f"<w:p>{runs}</w:p>"


def _docx(body: list[str], header: list[str] = ()) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("[Content_Types].xml", "<Types/>")
        z.writestr(
            "word/document.xml",
            f"<w:document {W}><w:body>{''.join(_para(l) for l in body)}</w:body></w:document>",
        )
        if header:
            z.writestr("word/header1.xml", f"<w:hdr {W}>{''.join(_para(l) for l in header)}</w:hdr>")
    return buf.getvalue()


def _att(name: str, raw: bytes, mime: str = "") -> dict:
    return {"name": name, "type": mime, "base64": base64.b64encode(raw).decode("ascii")}


def _parse(att: dict) -> dict:
    return parse_resume_into_profile({}, {"defaultResume": att}, force=True)["profile"]


def test_contact_details_in_a_word_header_are_read():
    profile = _parse(_att("r.docx", _docx(PM_LINES[2:], header=PM_LINES[:2])))
    assert profile["fullName"] == "Jordan Lee"
    assert profile["email"] == "jordan.lee@example.com"
    assert profile["phone"] == "(512) 555-0199"


def test_tab_aligned_dates_in_word_still_give_jobs():
    body = list(PM_LINES)
    body[5] = "Senior Product Manager, Acme Cloud\tJan 2021 - Present"
    del body[6]
    profile = _parse(_att("r.docx", _docx(body)))
    first = profile["workExperience"][0]
    assert first["company"] == "Acme Cloud"
    assert first["jobTitle"] == "Senior Product Manager"
    assert first["startDate"] == "01/2021"


def test_a_corrupt_word_file_is_refused_not_read_as_garbage():
    att = _att("r.docx", b"PK\x03\x04garbage" * 20)
    with pytest.raises(ValueError, match="Word"):
        read_resume_text(att)
    assert extract_text_from_attachment(att) == ""


def test_old_doc_files_get_a_clear_save_as_message():
    raw = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 64 + PM_TEXT.encode("utf-16-le")
    att = _att("r.doc", raw, "application/msword")
    with pytest.raises(ValueError, match="DOCX or PDF"):
        _parse(att)
    assert extract_text_from_attachment(att) == ""


def test_utf16_text_files_are_decoded():
    profile = _parse(_att("r.txt", PM_TEXT.encode("utf-16"), "text/plain"))
    assert profile["fullName"] == "Jordan Lee"
    assert profile["email"] == "jordan.lee@example.com"


def test_rtf_resumes_are_read_as_text():
    body = "".join(line.replace("—", "\\u8212?") + "\\par\n" for line in PM_LINES)
    raw = ("{\\rtf1\\ansi{\\fonttbl{\\f0 Calibri;}}\\f0\\fs22 " + body + "}").encode()
    profile = _parse(_att("r.rtf", raw, "application/rtf"))
    assert profile["fullName"] == "Jordan Lee"
    assert profile["email"] == "jordan.lee@example.com"
    assert profile["workExperience"][0]["company"] == "Acme Cloud"
    assert "rtf" not in profile["fullName"].lower()


def test_unknown_binary_files_are_refused():
    att = _att("r.pages", bytes(range(256)) * 8)
    with pytest.raises(ValueError, match="Could not extract text"):
        _parse(att)


@pytest.mark.parametrize(
    ("line", "title", "company", "location"),
    [
        ("Senior Product Manager, Acme Cloud — Austin, TX", "Senior Product Manager", "Acme Cloud", "Austin, TX"),
        ("Technical Program Manager at Northwind | Seattle, WA", "Technical Program Manager", "Northwind", "Seattle, WA"),
        ("Acme Cloud — Senior Product Manager", "Senior Product Manager", "Acme Cloud", None),
    ],
)
def test_title_company_and_location_are_split(line, title, company, location):
    entry = parse_experience([line, "Jan 2021 - Present"])[0]
    assert entry["jobTitle"] == title
    assert entry["company"] == company
    assert entry.get("location") == location


def test_an_em_dash_education_line_keeps_school_degree_and_year_apart():
    # The field of study is deliberately left unread without an "in"/"of"
    # clause (see test_resume_structure.test_an_absent_field_is_omitted...).
    entry = parse_education(["University of Texas at Austin — B.S. Computer Science, 2017"])[0]
    assert entry["school"] == "University of Texas at Austin"
    assert entry["degree"] == "Bachelor's Degree"
    assert entry["endDate"] == "2017"


def test_the_name_is_never_a_section_heading():
    profile, _ = parse_resume_fields("SUMMARY\nJordan Lee\njordan.lee@example.com\n", {})
    assert profile["fullName"] == "Jordan Lee"


def test_the_name_is_left_unknown_rather_than_guessed_from_contact_lines():
    profile, _ = parse_resume_fields("jordan.lee@example.com | (512) 555-0199\nEXPERIENCE\n", {})
    assert not profile.get("fullName")


def test_no_break_spaces_and_soft_hyphens_do_not_hide_phone_and_dates():
    """Some PDF exports write spaces as U+00A0 and hyphens as U+00AD, which
    made the phone number and every job date unreadable."""
    text = PM_TEXT.replace(" ", "\u00a0").replace("-", "\u00ad")
    profile = _parse(_att("r.txt", text.encode("utf-8"), "text/plain"))
    assert profile["fullName"] == "Jordan Lee"
    assert profile["phone"] == "(512) 555-0199"
    assert profile["workExperience"][0]["startDate"] == "01/2021"


def _pdf(columns: list[tuple[tuple[int, int, int, int], list[str]]]) -> bytes:
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    page = doc.new_page()
    for rect, lines in columns:
        page.insert_textbox(pymupdf.Rect(*rect), "\n".join(lines), fontsize=9)
    return doc.tobytes()


ASCII_LINES = [line.replace(" — ", " | ") for line in PM_LINES]


@pytest.mark.parametrize("layout", ["single", "two-column"])
def test_pdf_resumes_single_and_two_column(layout):
    if layout == "single":
        raw = _pdf([((50, 50, 560, 800), ASCII_LINES)])
    else:
        side = ASCII_LINES[10:]  # education + skills in a left sidebar
        main = ASCII_LINES[2:10]
        raw = _pdf([((50, 40, 560, 90), ASCII_LINES[:2]), ((40, 100, 200, 800), side), ((220, 100, 570, 800), main)])
    profile = _parse(_att("r.pdf", raw, "application/pdf"))
    assert profile["fullName"] == "Jordan Lee"
    assert profile["phone"] == "(512) 555-0199"
    jobs = profile["workExperience"]
    assert [j["company"] for j in jobs] == ["Acme Cloud", "Brightline Analytics"]
    assert jobs[0]["jobTitle"] == "Senior Product Manager"
    assert profile["education"][0]["degree"] == "Bachelor's Degree"
    assert "SQL" in profile["skills"]


def test_a_scanned_pdf_says_it_has_no_text():
    pymupdf = pytest.importorskip("pymupdf")
    doc = pymupdf.open()
    doc.new_page().draw_rect(pymupdf.Rect(50, 50, 300, 100), fill=(0, 0, 0))
    with pytest.raises(ValueError, match="scan"):
        _parse(_att("r.pdf", doc.tobytes(), "application/pdf"))


def test_the_resume_scanner_reads_word_files_instead_of_garbage():
    """The scanner page had its own extractor that decoded DOCX zip bytes as
    UTF-8, so a Word resume was scanned as binary noise."""
    from app.services.resume_intelligence.scanner import extract_text_from_upload

    att = _att("r.docx", _docx(PM_LINES))
    text = extract_text_from_upload(base64_data=att["base64"], filename="r.docx")
    assert "jordan.lee@example.com" in text
    assert "word/document.xml" not in text and "PK" not in text[:4]
    with pytest.raises(ValueError, match="Word"):
        extract_text_from_upload(base64_data=_att("r.docx", b"PK\x03\x04junk" * 20)["base64"], filename="r.docx")
