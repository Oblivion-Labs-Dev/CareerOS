"""Deterministic DOCX renderer and Word-based page measurement.

The golden DOCX owns every visual property. Rendering deep-copies the golden package, rebuilds the body
from the template's own paragraphs (headings, role headers, separators and education verbatim; bullets cloned
from each section's prototype paragraph with only the run text replaced) and copies every other part byte for
byte. Word converts the result to PDF; page count, per-bullet line counts and the preview all come from that PDF.
"""
from __future__ import annotations

import io
import math
import re
import statistics
import zipfile
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any
from xml.sax.saxutils import escape, quoteattr

from lxml import etree

from app.services.career_compiler.docx_template import (
    PKG_REL_NS, is_bold, para_text, read_parts, runs, w,
)
from app.services.career_compiler.metrics import Run, lead_runs, line_count, project_runs, skill_runs, summary_runs
from app.services.career_compiler.models import ResumeDocument

W14 = "http://schemas.microsoft.com/office/word/2010/wordml"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TRACE_PART = "customXml/careeros-trace.xml"
TRACE_REL_ID = "rIdCareerOSTrace"
TRACE_NS = "urn:careeros:resume-trace:v1"
ZIP_TIME = (1980, 1, 1, 0, 0, 0)


@dataclass
class Block:
    """One body paragraph of the rendered resume, in order."""
    key: str
    kind: str  # heading | summary | role_header | separator | bullet | education | project | skills
    text: str
    runs: list[Run] = field(default_factory=list)
    x: str = "bullet"  # which text column the paragraph starts in: bullet | body


@dataclass
class Rendered:
    docx: bytes
    blocks: list[Block]


def _norm(text: str) -> str:
    return "".join(ch for ch in text.casefold() if ch.isalnum())


def _with_bold(rpr: etree._Element | None, bold: bool) -> etree._Element:
    out = deepcopy(rpr) if rpr is not None else etree.Element(w("rPr"))
    for tag in ("b", "bCs"):
        for el in out.findall(w(tag)):
            out.remove(el)
    if bold:
        anchor = sum(1 for el in out if el.tag in (w("rStyle"), w("rFonts")))
        out.insert(anchor, etree.Element(w("bCs")))
        out.insert(anchor, etree.Element(w("b")))
    return out


def _prototype_formats(p: etree._Element) -> tuple[etree._Element, etree._Element]:
    """The bold and normal run properties a prototype paragraph uses for its visible text."""
    bold = normal = None
    for text, rpr in runs(p):
        if not text.strip():
            continue
        if is_bold(rpr) and bold is None:
            bold = rpr
        if not is_bold(rpr) and normal is None:
            normal = rpr
    bold = deepcopy(bold) if bold is not None else _with_bold(normal, True)
    normal = deepcopy(normal) if normal is not None else _with_bold(bold, False)
    return bold, normal


def _fill(prototype: etree._Element, content: list[Run]) -> etree._Element:
    p = deepcopy(prototype)
    for child in list(p):
        if child.tag != w("pPr"):
            p.remove(child)
    bold, normal = _prototype_formats(prototype)
    for text, is_b in content:
        if not text:
            continue
        r = etree.SubElement(p, w("r"))
        r.append(deepcopy(bold if is_b else normal))
        t = etree.SubElement(r, w("t"))
        t.text = text
        t.set(f"{{{XML_NS}}}space", "preserve")
    return p


def _tidy(p: etree._Element, n: int) -> etree._Element:
    """Drop Word's hidden bookmarks (their pairs no longer exist) and give every paragraph a unique id."""
    for el in list(p.iter(w("bookmarkStart"), w("bookmarkEnd"))):
        el.getparent().remove(el)
    if p.get(f"{{{W14}}}paraId") is not None:
        p.set(f"{{{W14}}}paraId", "%08X" % (0x10000000 + n))
    if p.get(f"{{{W14}}}textId") is not None:
        p.set(f"{{{W14}}}textId", "%08X" % (0x20000000 + n))
    return p


def _trace_xml(document: ResumeDocument) -> bytes:
    items = ([document.summary] if document.summary else []) + document.bullets()
    lines = [f'<trace xmlns="{TRACE_NS}" jd={quoteattr(document.jd_id)} store={quoteattr(document.store_digest)} '
             f'template={quoteattr(document.template_digest)}>']
    for b in items:
        reqs = " ".join(r["id"] for r in b.requirements if isinstance(r, dict) and r.get("id"))
        lines.append(f"<bullet id={quoteattr(b.id)} project={quoteattr(b.project_id)} requirements={quoteattr(reqs)} "
                     f"evidence={quoteattr(' '.join(b.evidence_ids))}>{escape(b.text)}</bullet>")
    lines.append("</trace>")
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n' + "\n".join(lines)).encode()


def _package(parts: dict[str, bytes]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as package:
        for name, data in parts.items():
            info = zipfile.ZipInfo(name, date_time=ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            package.writestr(info, data)
    return out.getvalue()


def _serialize(root: etree._Element) -> bytes:
    return etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)


def render_docx(document: ResumeDocument, spec: dict[str, Any], golden: bytes, *, trace: bool = True) -> Rendered:
    """Fill the golden template with resume.json text. Formatting comes only from the golden paragraphs."""
    parts = read_parts(golden)
    root = etree.fromstring(parts["word/document.xml"])
    body = root.find(w("body"))
    source = list(body)
    sect = body.find(w("sectPr"))
    for child in source:
        body.remove(child)
    slots, lead = spec["slots"], spec["runs"]["lead"]
    headings = slots["headings"]
    blocks: list[Block] = []

    def put(p: etree._Element, block: Block) -> None:
        body.append(_tidy(p, len(blocks) + 1))
        blocks.append(block)

    def verbatim(index: int, key: str, kind: str) -> None:
        put(deepcopy(source[index]), Block(key, kind, para_text(source[index]), x="body"))

    def filled(index: int, key: str, kind: str, content: list[Run], x: str = "bullet") -> None:
        put(_fill(source[index], content), Block(key, kind, "".join(t for t, _ in content), content, x))

    if document.summary and document.summary.text.strip():
        verbatim(headings["summary"], "heading:summary", "heading")
        filled(slots["summary"], "summary", "summary", summary_runs(document.summary.text), x="body")
    verbatim(headings["experience"], "heading:experience", "heading")
    sections = {s.employment_id: s for s in document.sections}
    visible = [r for r in slots["roles"] if r["employment_id"] and r["prototype"] is not None
               and (r["slot"] != "earlier_experience" or (sections.get(r["employment_id"]) and sections[r["employment_id"]].bullets))]
    for position, role in enumerate(visible):
        if position and position - 1 < len(slots["separators"]):
            verbatim(slots["separators"][position - 1], f"separator:{position}", "separator")
        verbatim(role["header"], f"role:{role['employment_id']}", "role_header")
        section = sections.get(role["employment_id"])
        for bullet in section.bullets if section else []:
            filled(role["prototype"], bullet.id, "bullet", lead_runs(bullet.text, lead))
    verbatim(headings["education"], "heading:education", "heading")
    for n, index in enumerate(slots["education"]):
        verbatim(index, f"education:{n}", "education")
    if document.featured and slots["projects"]["prototype"] is not None:
        verbatim(headings["projects"], "heading:projects", "heading")
        for item in document.featured:
            filled(slots["projects"]["prototype"], item.id, "project", project_runs(item.name, item.text))
    lines = [(line, document.skills.get(line["group"]) or []) for line in slots["skills"]["lines"]]
    if any(items for _, items in lines):
        verbatim(headings["skills"], "heading:skills", "heading")
        for line, items in lines:
            if items:
                filled(line["paragraph"], f"skills:{line['group']}", "skills",
                       skill_runs(line["label"], items, slots["skills"]["separator"]))
    body.append(deepcopy(sect))
    parts["word/document.xml"] = _serialize(root)
    if trace:
        rels = etree.fromstring(parts["word/_rels/document.xml.rels"])
        rel = etree.SubElement(rels, f"{{{PKG_REL_NS}}}Relationship")
        rel.set("Id", TRACE_REL_ID)
        rel.set("Type", "http://schemas.openxmlformats.org/officeDocument/2006/relationships/customXml")
        rel.set("Target", "../" + TRACE_PART)
        parts["word/_rels/document.xml.rels"] = _serialize(rels)
        parts[TRACE_PART] = _trace_xml(document)
    return Rendered(_package(parts), blocks)


def _bare(p: etree._Element) -> str:
    """A paragraph without its ids and hidden bookmarks, for comparing verbatim template paragraphs."""
    p = deepcopy(p)
    for name in (f"{{{W14}}}paraId", f"{{{W14}}}textId"):
        p.attrib.pop(name, None)
    for el in list(p.iter(w("bookmarkStart"), w("bookmarkEnd"))):
        el.getparent().remove(el)
    return etree.tostring(p, method="c14n").decode()


def formatting_drift(docx: bytes, golden: bytes) -> list[str]:
    """Every way a rendered DOCX departs from the golden's formatting. Text differences are not drift.

    Locked parts (styles, numbering, settings, header, footer, theme, fonts) must be byte-identical, section
    properties identical, every paragraph and run property set must exist in the golden, and template paragraphs
    (headings, role headers, separators, education) must be verbatim."""
    from app.services.career_compiler.docx_template import DATES, LOCKED_PARTS, canonical, paragraph_kind
    out, gold, mine = [], read_parts(golden), read_parts(docx)
    for name in LOCKED_PARTS + ("[Content_Types].xml",):
        if name in gold and gold[name] != mine.get(name):
            out.append(f"{name} differs from the template.")
    gold_rels = {(r.get("Id"), r.get("Target")) for r in etree.fromstring(gold["word/_rels/document.xml.rels"])}
    mine_rels = {(r.get("Id"), r.get("Target")) for r in etree.fromstring(mine["word/_rels/document.xml.rels"])}
    if not gold_rels <= mine_rels:
        out.append("document relationships lost a template relationship.")
    g_body = etree.fromstring(gold["word/document.xml"]).find(w("body"))
    m_body = etree.fromstring(mine["word/document.xml"]).find(w("body"))
    if canonical(g_body.find(w("sectPr"))) != canonical(m_body.find(w("sectPr"))):
        out.append("Section properties (page size, margins, header/footer references) changed.")
    g_paras = [p for p in g_body if p.tag == w("p")]
    ppr = {canonical(p.find(w("pPr"))) for p in g_paras if p.find(w("pPr")) is not None}
    rpr = {canonical(r.find(w("rPr"))) for p in g_paras for r in p.iter(w("r")) if r.find(w("rPr")) is not None}
    fixed: dict[str, set[str]] = {}
    for p in g_paras:
        if paragraph_kind(p) in ("heading", "separator", "role_header") or (paragraph_kind(p) == "bullet" and DATES.search(para_text(p))):
            fixed.setdefault(para_text(p), set()).add(_bare(p))
    for n, el in enumerate(m_body):
        if el.tag == w("sectPr"):
            continue
        if el.tag != w("p"):
            out.append(f"Body element {n} is {etree.QName(el).localname}, not a paragraph.")
            continue
        if el.find(w("pPr")) is None or canonical(el.find(w("pPr"))) not in ppr:
            out.append(f"Paragraph {n} ('{para_text(el)[:40]}') has paragraph formatting not in the template.")
        for r in el.iter(w("r")):
            if r.find(w("rPr")) is None or canonical(r.find(w("rPr"))) not in rpr:
                out.append(f"Paragraph {n} ('{para_text(el)[:40]}') has run formatting not in the template.")
                break
        text = para_text(el)
        if text in fixed and _bare(el) not in fixed[text]:
            out.append(f"Template paragraph '{text.strip()[:40]}' was altered.")
    return out


def read_trace(docx: bytes) -> dict[str, dict[str, Any]]:
    """Bullet metadata embedded in a rendered DOCX: id -> requirement ids, evidence ids, text."""
    parts = read_parts(docx)
    if TRACE_PART not in parts:
        return {}
    root = etree.fromstring(parts[TRACE_PART])
    return {b.get("id"): {"project": b.get("project"), "requirements": (b.get("requirements") or "").split(),
                          "evidence": (b.get("evidence") or "").split(), "text": b.text or ""}
            for b in root.iter(f"{{{TRACE_NS}}}bullet")}


# ---------------------------------------------------------------------------------------------- measurement


@dataclass
class Row:
    """Spans sharing a baseline on one page. Bullet glyphs are kept in `spans` but carry no letters."""
    page: int
    spans: list[dict]

    @property
    def text(self) -> str:
        return "".join(s["text"] for s in self.spans)

    @property
    def norm(self) -> str:
        return _norm(self.text)

    @property
    def y0(self) -> float:
        return min(s["bbox"][1] for s in self.spans)

    @property
    def y1(self) -> float:
        return max(s["bbox"][3] for s in self.spans)

    @property
    def baseline(self) -> float:
        return next((s["origin"][1] for s in self.spans if _norm(s["text"])), self.spans[0]["origin"][1])

    @property
    def x0(self) -> float:
        return min((s["bbox"][0] for s in self.spans if _norm(s["text"])), default=1e9)

    @property
    def x1(self) -> float:
        return max(s["bbox"][2] for s in self.spans)


def pdf_rows(pdf: bytes) -> tuple[list[Row], int, tuple[float, float]]:
    """Visible text rows per page, top to bottom."""
    import pymupdf
    rows: list[Row] = []
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        size = (doc[0].rect.width, doc[0].rect.height)
        for number, page in enumerate(doc, start=1):
            spans = [s for b in page.get_text("dict")["blocks"] if b["type"] == 0 for l in b["lines"] for s in l["spans"]
                     if s["text"].strip()]
            spans.sort(key=lambda s: (round(s["origin"][1], 1), s["bbox"][0]))
            for s in spans:
                if rows and rows[-1].page == number and abs(rows[-1].spans[-1]["origin"][1] - s["origin"][1]) < 1.2:
                    rows[-1].spans.append(s)
                else:
                    rows.append(Row(number, [s]))
        return rows, len(doc), size


def match_blocks(blocks: list[Block], rows: list[Row]) -> dict[str, list[Row]]:
    """Assign PDF rows to paragraphs by walking both in reading order on letters and digits only."""
    stream, owner = [], []
    for i, row in enumerate(rows):
        stream.append(row.norm)
        owner.extend([i] * len(row.norm))
    text = "".join(stream)
    out: dict[str, list[Row]] = {}
    cursor = 0
    for block in blocks:
        target = _norm(block.text)
        if not target:
            continue
        at = text.find(target, cursor)
        if at < 0:
            continue
        hit = sorted(set(owner[at:at + len(target)]))
        out[block.key] = [rows[i] for i in hit]
        cursor = at + len(target)
    return out


@dataclass
class Measurement:
    engine: str
    pages: int
    lines: dict[str, int]
    last_fill: dict[str, float]
    total_lines: int
    capacity_lines: int
    overflow_lines: int
    spare_lines: int
    unmatched: list[str] = field(default_factory=list)
    pdf: bytes | None = None

    @property
    def fits(self) -> bool:
        return self.pages == 1

    def summary(self) -> dict[str, Any]:
        return {"engine": self.engine, "pages": self.pages, "fits": self.fits, "lines_used": self.total_lines,
                "capacity_lines": self.capacity_lines, "overflow_lines": self.overflow_lines,
                "spare_lines": self.spare_lines, "unmatched": self.unmatched}


def _chrome(rows: list[Row], geometry: dict[str, Any]) -> list[Row]:
    """Rows inside the body area (header and footer excluded) on every page."""
    return [r for r in rows if r.y0 >= geometry["body_top"] - 2 and r.y1 <= geometry["footer_top"] - .5]


def measure_pdf(pdf: bytes, blocks: list[Block], geometry: dict[str, Any], engine: str) -> Measurement:
    rows, pages, _ = pdf_rows(pdf)
    body = _chrome(rows, geometry)
    matched = match_blocks(blocks, [r for r in body if r.norm])
    right = geometry["right_x"]
    lines, fill = {}, {}
    for key, found in matched.items():
        lines[key] = len(found)
        start = found[0].x0 if found[0].x0 < 1e8 else geometry["bullet_text_x"]
        fill[key] = round(max(0.0, min(1.0, (found[-1].x1 - start) / max(right - start, 1))), 3)
    total = sum(lines.get(b.key, 1) for b in blocks)
    page_one = [r for r in body if r.page == 1]
    bottom = max((r.y1 for r in page_one), default=geometry["body_top"])
    spare = 0 if pages > 1 else max(0, math.floor((geometry["body_limit"] - bottom) / geometry["bullet_pitch"] + .25))
    overflow = len({(r.page, round(r.y0)) for r in body if r.page > 1})
    unmatched = [b.key for b in blocks if _norm(b.text) and b.key not in matched]
    return Measurement(engine, pages, lines, fill, total, geometry["capacity_lines"], overflow, spare, unmatched, pdf)


class WordMeasurer:
    """Page measurement by the layout authority (Word, or LibreOffice where Word is not installed)."""

    def __init__(self, spec: dict[str, Any], converter=None):
        from app.services.career_compiler.word import get_converter
        if "rendered" not in spec:
            raise ValueError("Template spec has no Word calibration. Run: python -m app.services.career_compiler.docx_template")
        self.geometry = spec["rendered"]
        self.converter = converter or get_converter()
        self.engine = self.converter.name

    def measure(self, rendered: Rendered) -> Measurement:
        return measure_pdf(self.converter.to_pdf(rendered.docx), rendered.blocks, self.geometry, self.engine)


class EstimateMeasurer:
    """Helvetica-metric estimate against the calibrated capacity. Used by planning and tests, never for export."""
    engine = "estimate"

    def __init__(self, spec: dict[str, Any]):
        self.spec = spec
        self.geometry = spec.get("rendered") or {}

    def block_lines(self, block: Block) -> tuple[int, float]:
        if not block.runs:
            return 1, 1.0
        geometry = self.geometry or {}
        width = geometry.get("text_width_bullet", 504.0) if block.x == "bullet" else geometry.get("text_width_body", 540.0)
        return line_count(block.runs, width, geometry.get("body_size", 8.0))

    def measure(self, rendered: Rendered) -> Measurement:
        lines, fill = {}, {}
        for block in rendered.blocks:
            lines[block.key], fill[block.key] = self.block_lines(block)
        total = sum(lines.values())
        capacity = self.geometry.get("capacity_lines", 74)
        pages = 1 if total <= capacity else 2
        return Measurement(self.engine, pages, lines, fill, total, capacity, max(0, total - capacity),
                           max(0, capacity - total))


def preview_png(pdf: bytes, page: int = 0, zoom: float = 2.0) -> bytes:
    import pymupdf
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return doc[min(page, len(doc) - 1)].get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("png")


def page_fonts(pdf: bytes) -> set[tuple[str, float]]:
    import pymupdf
    with pymupdf.open(stream=pdf, filetype="pdf") as doc:
        return {(s["font"].split("+")[-1], round(s["size"], 2)) for page in doc for b in page.get_text("dict")["blocks"]
                if b["type"] == 0 for l in b["lines"] for s in l["spans"] if s["text"].strip()}


# ---------------------------------------------------------------------------------------------- calibration


def golden_document(spec: dict[str, Any], golden: bytes) -> ResumeDocument:
    """The golden resume's own text as resume.json, for round-trip and regression checks (not evidence)."""
    from app.services.career_compiler.models import Bullet, Section
    children = list(etree.fromstring(read_parts(golden)["word/document.xml"]).find(w("body")))
    text = lambda i: para_text(children[i]).strip()
    slots = spec["slots"]
    sections = [Section(employment_id=r["employment_id"], company="", role=r["text"],
                        bullets=[Bullet(id=f"p{i}", employment_id=r["employment_id"], project_id=f"p{i}", text=text(i))
                                 for i in r["bullets"]]) for r in slots["roles"]]
    featured = [Bullet(id=f"p{i}", employment_id="personal", project_id=f"p{i}", name=text(i).split(":", 1)[0],
                       text=text(i).split(":", 1)[1].strip()) for i in slots["projects"]["entries"]]
    skills = {l["group"]: text(l["paragraph"]).split(":", 1)[1].strip().split(slots["skills"]["separator"].strip())
              for l in slots["skills"]["lines"]}
    skills = {g: [s.strip() for s in items if s.strip()] for g, items in skills.items()}
    summary = Bullet(id="summary", employment_id="", project_id="", text=text(slots["summary"]))
    return ResumeDocument(store_digest="golden", template_digest=spec["golden"]["sha256"][:16], summary=summary,
                          sections=sections, featured=featured, skills=skills)


def golden_blocks(spec: dict[str, Any], golden: bytes) -> list[Block]:
    root = etree.fromstring(read_parts(golden)["word/document.xml"])
    children = list(root.find(w("body")))
    return [Block(f"p{p['index']}", p["kind"], para_text(children[p["index"]])) for p in spec["paragraphs"]]


def geometry_of(pdf: bytes, spec: dict[str, Any]) -> dict[str, Any]:
    """Word-rendered geometry of a document built from this template: positions, fonts, pitch, chrome."""
    rows, pages, (width, height) = pdf_rows(pdf)
    header_norms = [_norm(p["text"]) for p in spec["header"]["paragraphs"] if _norm(p["text"])]
    footer_norms = [_norm(p["text"]) for p in spec["footer"]["paragraphs"] if _norm(p["text"])]
    first = [r for r in rows if r.page == 1]
    header_rows = [r for r in first if any(n.startswith(r.norm[:12]) for n in header_norms) and r.norm and r.y1 < height / 4]
    footer_rows = [r for r in first if any(n.startswith(r.norm[:12]) for n in footer_norms) and r.norm and r.y0 > height * .75]
    header_bottom = max(r.y1 for r in header_rows)
    footer_top = min(r.y0 for r in footer_rows)
    body = [r for r in first if header_bottom < r.y0 and r.y1 < footer_top]
    glyphs = sorted({round(s["bbox"][0], 1) for r in body for s in r.spans if not _norm(s["text"]) and s["text"].strip() in ("\u2022", "\uf0b7")})
    text_x = sorted({round(r.x0, 1) for r in body if r.x0 < 1e8})
    has_glyph = lambda row: any(not _norm(s["text"]) and s["text"].strip() in ("\u2022", "\uf0b7") for s in row.spans)
    column = round((spec["margins"]["left"]["twips"] + next(iter(spec["bullets"].values()))["indent_left_twips"]) / 20, 1)
    in_column = lambda row: abs(row.x0 - column) < 1
    pairs = [(a, b) for a, b in zip(body, body[1:]) if 8 < b.baseline - a.baseline < 12]
    wrapped = [b.baseline - a.baseline for a, b in pairs if not has_glyph(b) and in_column(a) and in_column(b)]
    bullets = [b.baseline - a.baseline for a, b in pairs if has_glyph(b) and in_column(a)]
    fonts = sorted({f"{s['font'].split('+')[-1]} {round(s['size'], 2):g}" for r in rows for s in r.spans})
    return {
        "engine": None, "pages": pages, "page_width_pt": round(width, 2), "page_height_pt": round(height, 2),
        "header_rows": [{"text": r.text.strip()[:60], "y0": round(r.y0, 1), "y1": round(r.y1, 1),
                         "font": r.spans[0]["font"], "size": round(r.spans[0]["size"], 2)} for r in header_rows],
        "footer_rows": [{"text": r.text.strip()[:60], "y0": round(r.y0, 1), "y1": round(r.y1, 1),
                         "font": r.spans[0]["font"], "size": round(r.spans[0]["size"], 2)} for r in footer_rows],
        "header_bottom": round(header_bottom, 1), "footer_top": round(footer_top, 1),
        "body_top": round(min(r.y0 for r in body), 1), "body_bottom": round(max(r.y1 for r in body), 1),
        "body_left_x": text_x[0] if text_x else None, "bullet_glyph_x": glyphs,
        "text_columns_x": text_x, "right_x": round(width - spec["margins"]["right"]["pt"], 2),
        "dates_x": sorted({round(s["bbox"][0], 1) for r in body for s in r.spans if re.match(r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) \d{4}", s["text"].strip()) and s["bbox"][0] > width / 2}),
        "line_pitch": round(statistics.median(wrapped), 2) if wrapped else None,
        "bullet_pitch": round(statistics.median(bullets), 2) if bullets else None,
        "fonts": fonts,
    }


def calibrate(spec: dict[str, Any], golden: bytes, converter=None) -> dict[str, Any]:
    """Measure the golden in Word: geometry, per-paragraph lines, and how many more lines fit on the page."""
    from app.services.career_compiler.word import get_converter
    converter = converter or get_converter()
    pdf = converter.to_pdf(golden)
    geometry = geometry_of(pdf, spec)
    geometry["engine"] = converter.name
    if geometry["pages"] != 1:
        raise ValueError(f"The golden template renders on {geometry['pages']} pages in {converter.name}; it must be one page.")
    blocks = golden_blocks(spec, golden)
    rows = [r for r in pdf_rows(pdf)[0] if r.page == 1 and geometry["header_bottom"] < r.y0 and r.y1 < geometry["footer_top"] and r.norm]
    matched = match_blocks(blocks, rows)
    lines = {b.key: len(matched.get(b.key, [])) or 1 for b in blocks}

    parts = read_parts(golden)
    root = etree.fromstring(parts["word/document.xml"])
    body = root.find(w("body"))
    probe_source = list(body)[spec["slots"]["skills"]["prototype"]]
    spare = 0
    for extra in range(1, 25):
        trial = deepcopy(root)
        trial_body = trial.find(w("body"))
        sect = trial_body.find(w("sectPr"))
        for _ in range(extra):
            sect.addprevious(_fill(probe_source, [("Probe", True)]))
        trial_parts = dict(parts)
        trial_parts["word/document.xml"] = _serialize(trial)
        probe_rows, probe_pages, _ = pdf_rows(converter.to_pdf(_package(trial_parts)))
        if probe_pages > 1:
            break
        spare = extra
    used = sum(lines.values())
    geometry.update({
        "golden_lines": used, "spare_lines": spare, "capacity_lines": used + spare,
        "body_limit": round(geometry["body_bottom"] + spare * geometry["bullet_pitch"], 1),
        "paragraph_lines": {k: v for k, v in lines.items()},
        "bullet_text_x": round(spec["margins"]["left"]["pt"] + int(next(iter(spec["bullets"].values()))["indent_left_twips"]) / 20, 2),
        "text_width_bullet": round(geometry["right_x"] - (spec["margins"]["left"]["pt"] + int(next(iter(spec["bullets"].values()))["indent_left_twips"]) / 20), 2),
        "text_width_body": round(geometry["right_x"] - spec["margins"]["left"]["pt"], 2),
        "body_size": 8.0,
    })
    return geometry
