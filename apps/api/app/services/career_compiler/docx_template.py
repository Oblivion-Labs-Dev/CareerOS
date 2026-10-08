"""Golden DOCX template: inspection into a slot spec, and loading it.

templates/akshay-one-page.docx is the visual authority. This module reads its XML and writes
templates/akshay-one-page.template.json, which documents the measured formatting and names the content
slots (prototype paragraphs) the renderer may fill. Nothing here changes the DOCX.

    python -m app.services.career_compiler.docx_template          # inspect + calibrate with Word
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import statistics
import zipfile
from functools import lru_cache
from pathlib import Path
from typing import Any

from lxml import etree

REPO_ROOT = Path(__file__).resolve().parents[5]
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
R_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
A_NS = "http://schemas.openxmlformats.org/drawingml/2006/main"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
HEADINGS = {"PROFESSIONAL SUMMARY": "summary", "EXPERIENCE": "experience", "EDUCATION": "education",
            "FEATURED PROJECTS": "projects", "SKILLS": "skills"}
MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
DATES = re.compile(rf"{MONTH}\s*\d{{4}}\s*(?:to|\u2013|-)\s*(?:{MONTH}\s*\d{{4}}|Present)")
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
ROLE_SLOTS = {"employment.microsoft": "microsoft", "employment.amazon": "amazon"}
#: Parts the renderer must copy byte for byte. Any change here is template drift.
LOCKED_PARTS = ("word/styles.xml", "word/numbering.xml", "word/settings.xml", "word/header1.xml", "word/footer1.xml",
                "word/_rels/header1.xml.rels", "word/_rels/footer1.xml.rels", "word/theme/theme1.xml",
                "word/fontTable.xml", "word/webSettings.xml", "word/footnotes.xml", "word/endnotes.xml")


def w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def val(el: etree._Element | None, name: str = "val") -> str | None:
    return None if el is None else el.get(w(name))


def golden_path() -> Path:
    return Path(os.environ.get("CAREEROS_RESUME_DOCX") or REPO_ROOT / "templates" / "akshay-one-page.docx")


def spec_path() -> Path:
    golden = golden_path()
    return golden.with_name(golden.stem + ".template.json")


def read_parts(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as package:
        return {info.filename: package.read(info.filename) for info in package.infolist()}


def para_text(p: etree._Element) -> str:
    out = []
    for el in p.iter(w("t"), w("tab"), w("br")):
        if el.tag == w("t"):
            out.append(el.text or "")
        else:
            out.append("\t" if el.tag == w("tab") else "\n")
    return "".join(out)


def runs(p: etree._Element) -> list[tuple[str, etree._Element | None]]:
    out = []
    for r in p.iter(w("r")):
        text = "".join((t.text or "") if t.tag == w("t") else "\t" for t in r if t.tag in (w("t"), w("tab")))
        if text:
            out.append((text, r.find(w("rPr"))))
    return out


def is_bold(rpr: etree._Element | None) -> bool:
    b = None if rpr is None else rpr.find(w("b"))
    return b is not None and val(b) not in ("0", "false")


def canonical(el: etree._Element) -> str:
    return etree.tostring(el, method="c14n").decode()


def twips_pt(value: str | None) -> float | None:
    return None if value is None else round(int(value) / 20, 2)


class _Styles:
    """Resolves effective run formatting: run -> paragraph style chain -> docDefaults -> theme fonts."""

    def __init__(self, styles_xml: bytes, theme_xml: bytes | None):
        self.root = etree.fromstring(styles_xml)
        self.by_id = {s.get(w("styleId")): s for s in self.root.iter(w("style"))}
        self.theme = {}
        if theme_xml:
            theme = etree.fromstring(theme_xml)
            for kind in ("major", "minor"):
                latin = theme.find(f".//{{{A_NS}}}{kind}Font/{{{A_NS}}}latin")
                if latin is not None:
                    self.theme[kind] = latin.get("typeface")

    def chain(self, style_id: str | None) -> list[etree._Element]:
        out, seen = [], set()
        while style_id and style_id in self.by_id and style_id not in seen:
            seen.add(style_id)
            style = self.by_id[style_id]
            out.append(style)
            style_id = val(style.find(w("basedOn")))
        return out

    def defaults(self, kind: str) -> etree._Element | None:
        return self.root.find(f"{w('docDefaults')}/{w(kind + 'Default')}/{w(kind)}")

    def font(self, rpr: etree._Element | None) -> str | None:
        fonts = None if rpr is None else rpr.find(w("rFonts"))
        if fonts is None:
            return None
        if val(fonts, "ascii"):
            return val(fonts, "ascii")
        theme = val(fonts, "asciiTheme") or ""
        return self.theme.get("major" if theme.startswith("major") else "minor") if theme else None

    def effective(self, rpr: etree._Element | None, style_id: str | None) -> dict[str, Any]:
        layers = [rpr] + [s.find(w("rPr")) for s in self.chain(style_id or "Normal")] + [self.defaults("rPr")]
        layers = [l for l in layers if l is not None]
        pick = lambda fn: next((v for v in (fn(l) for l in layers) if v is not None), None)
        size = pick(lambda l: val(l.find(w("sz"))))
        bold = pick(lambda l: (val(l.find(w("b"))) not in ("0", "false")) if l.find(w("b")) is not None else None)
        return {"font": pick(self.font), "size_pt": int(size) / 2 if size else None, "bold": bool(bold),
                "underline": pick(lambda l: val(l.find(w("u")))),
                "color": pick(lambda l: val(l.find(w("color"))))}


def describe_ppr(ppr: etree._Element | None) -> dict[str, Any]:
    if ppr is None:
        return {}
    out: dict[str, Any] = {}
    if (style := val(ppr.find(w("pStyle")))):
        out["style"] = style
    num = ppr.find(w("numPr"))
    if num is not None:
        out["numbering"] = {"numId": val(num.find(w("numId"))), "ilvl": val(num.find(w("ilvl")))}
    spacing = ppr.find(w("spacing"))
    if spacing is not None:
        out["spacing"] = {k: spacing.get(w(k)) for k in ("before", "after", "line", "lineRule", "beforeAutospacing",
                                                          "afterAutospacing") if spacing.get(w(k)) is not None}
    ind = ppr.find(w("ind"))
    if ind is not None:
        out["indent_twips"] = {k: ind.get(w(k)) for k in ("left", "right", "hanging", "firstLine") if ind.get(w(k))}
    if (jc := val(ppr.find(w("jc")))):
        out["alignment"] = jc
    for flag in ("contextualSpacing", "keepNext", "keepLines"):
        if ppr.find(w(flag)) is not None:
            out[flag] = True
    tabs = ppr.find(w("tabs"))
    if tabs is not None:
        out["tabs"] = [{"val": val(t), "pos": val(t, "pos")} for t in tabs]
    return out


def describe_runs(p: etree._Element, styles: _Styles) -> list[dict[str, Any]]:
    """Consecutive runs with identical effective formatting merged, text shortened."""
    style = val(p.find(f"{w('pPr')}/{w('pStyle')}"))
    out: list[dict[str, Any]] = []
    for text, rpr in runs(p):
        fmt = styles.effective(rpr, style)
        if out and {k: v for k, v in out[-1].items() if k != "text"} == fmt:
            out[-1]["text"] += text
        else:
            out.append({"text": text, **fmt})
    for item in out:
        shown = item["text"].replace("\t", "\u2192")
        item["text"] = shown if len(shown) <= 60 else shown[:57] + "..."
    return out


def paragraph_kind(p: etree._Element) -> str:
    text = para_text(p)
    numbered = p.find(f"{w('pPr')}/{w('numPr')}") is not None
    label = re.sub(r"[_\s]+", " ", text).strip()
    if not numbered and label in HEADINGS:
        return "heading"
    if not numbered and not text.replace("_", "").strip():
        return "separator"
    if not numbered and "|" in text and DATES.search(text):
        return "role_header"
    return "bullet" if numbered else "paragraph"


def _month(value: str) -> str:
    try:
        year, mon = str(value).split("-")[:2]
        return f"{MONTHS[int(mon) - 1]} {year}"
    except (ValueError, IndexError):
        return str(value or "Present")


def _role_header(p: etree._Element, styles: _Styles) -> dict[str, Any]:
    text = para_text(p)
    dates = DATES.search(text)
    before = text[:dates.start()] if dates else text
    title = before.split("\t")[0].strip()
    gap = before[len(before.split("\t")[0]):]
    return {"text": title, "dates": dates.group(0) if dates else "",
            "alignment": {"tabs": gap.count("\t"), "spaces": len(gap) - len(gap.rstrip(" ")),
                          "method": "dates pushed right with literal tabs and spaces (no right tab stop)"},
            "runs": describe_runs(p, styles)}


def _lead(p: etree._Element) -> str:
    lead = ""
    for text, rpr in runs(p):
        if not is_bold(rpr):
            break
        lead += text
    return lead


def _header_footer(xml: bytes, rels_xml: bytes | None, styles: _Styles) -> dict[str, Any]:
    root = etree.fromstring(xml)
    rels = {}
    if rels_xml:
        rels = {r.get("Id"): r.get("Target") for r in etree.fromstring(rels_xml)}
    paragraphs = []
    for p in root.iter(w("p")):
        links = [{"text": para_text(h), "target": rels.get(h.get(f"{{{R_NS}}}id"))} for h in p.iter(w("hyperlink"))]
        paragraphs.append({"text": para_text(p), **describe_ppr(p.find(w("pPr"))), "runs": describe_runs(p, styles),
                           **({"links": links} if links else {})})
    return {"paragraphs": paragraphs}


def inspect(data: bytes, employment: dict[str, dict[str, Any]] | None = None,
            education: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Measure the golden DOCX and name its slots. `employment`/`education` (from career.json) map role
    headers to employment ids and flag any template text that disagrees with the canonical facts."""
    parts = read_parts(data)
    styles = _Styles(parts["word/styles.xml"], parts.get("word/theme/theme1.xml"))
    root = etree.fromstring(parts["word/document.xml"])
    body = root.find(w("body"))
    children = list(body)
    sect = body.find(w("sectPr"))
    pg, mar = sect.find(w("pgSz")), sect.find(w("pgMar"))
    employment = employment or {}
    checks: list[str] = []

    paragraphs, section = [], ""
    slots: dict[str, Any] = {"headings": {}, "summary": None, "roles": [], "separators": [], "education": [],
                             "projects": {"entries": []}, "skills": {"lines": []}}
    role: dict[str, Any] | None = None
    for index, child in enumerate(children):
        if child.tag != w("p"):
            continue
        kind = paragraph_kind(child)
        text = para_text(child)
        if kind == "heading":
            section = HEADINGS[re.sub(r"[_\s]+", " ", text).strip()]
            slots["headings"][section] = index
        elif kind == "separator" and section == "experience":
            slots["separators"].append(index)
        elif kind == "role_header":
            header = _role_header(child, styles)
            match = next((eid for eid, job in employment.items() if job.get("company", "").casefold() in text.casefold()), None)
            role = {"employment_id": match, "slot": ROLE_SLOTS.get(match or "", "earlier_experience"),
                    "header": index, "bullets": [], **header}
            slots["roles"].append(role)
            if match:
                job = employment[match]
                expected = f"{_month(job.get('start', ''))} to {_month(job.get('end', ''))}"
                if re.sub(r"\s*(\u2013|-)\s*", " to ", header["dates"]) != expected:
                    checks.append(f"Role header for {match} shows '{header['dates']}', career.json says '{expected}'.")
                if job.get("location") and job["location"] not in text:
                    checks.append(f"Role header for {match} does not show career.json location '{job['location']}'.")
                if header["text"].split(" | ")[0] not in job.get("role", ""):
                    checks.append(f"Role header title '{header['text'].split(' | ')[0]}' differs from career.json role "
                                  f"'{job.get('role')}'.")
            else:
                checks.append(f"Role header '{header['text']}' matches no career.json employment.")
        elif kind == "bullet" and section == "experience" and role is not None:
            role["bullets"].append(index)
        elif kind == "bullet" and section == "education":
            slots["education"].append(index)
        elif kind == "bullet" and section == "projects":
            slots["projects"]["entries"].append(index)
        elif kind == "bullet" and section == "skills":
            label = runs(child)[0][0].strip()
            group = next((g for g in ("languages", "architecture_systems", "cloud_platform", "ai_ml_security")
                          if label.casefold().replace("/", " ").split()[0].startswith(g.split("_")[0])), label)
            slots["skills"]["lines"].append({"paragraph": index, "label": label, "group": group})
        elif kind == "paragraph" and section == "summary":
            slots["summary"] = index
        paragraphs.append({"index": index, "section": section, "kind": kind, **describe_ppr(child.find(w("pPr"))),
                           "runs": describe_runs(child, styles)})

    for entry in slots["education"]:
        text = para_text(children[entry])
        school = next((e for e in education or [] if e.get("institution") and e["institution"] in text), None)
        if school is None:
            checks.append(f"Education line '{text.strip()[:60]}' matches no career.json education record.")
        elif f"{_month(school.get('start', ''))} to {_month(school.get('end', ''))}".replace(" ", "") not in text.replace(" ", ""):
            checks.append(f"Education dates for {school['institution']} differ from career.json.")
    for role in slots["roles"]:
        role["prototype"] = role["bullets"][0] if role["bullets"] else None
    slots["projects"]["prototype"] = (slots["projects"]["entries"] or [None])[0]
    slots["skills"]["prototype"] = (slots["skills"]["lines"] or [{"paragraph": None}])[0]["paragraph"]
    skill_text = " ".join(para_text(children[l["paragraph"]]) for l in slots["skills"]["lines"])
    slots["skills"]["separator"] = " \u2022 " if " \u2022 " in skill_text else ", "

    experience = [i for r in slots["roles"] for i in r["bullets"]]
    leads = sorted(len(_lead(children[i]).rstrip()) for i in experience if _lead(children[i]))
    exemplars = [{"section": "experience", "text": para_text(children[i]).strip()} for i in experience]
    exemplars += [{"section": "projects", "text": para_text(children[i]).split(":", 1)[-1].strip()}
                  for i in slots["projects"]["entries"]]

    numbering = etree.fromstring(parts["word/numbering.xml"])
    abstract = {a.get(w("abstractNumId")): a for a in numbering.iter(w("abstractNum"))}
    used = sorted({p["numbering"]["numId"] for p in paragraphs if "numbering" in p}, key=int)
    lists = {}
    for num in numbering.iter(w("num")):
        if num.get(w("numId")) in used:
            lvl = abstract[val(num.find(w("abstractNumId")))].find(w("lvl"))
            ind = lvl.find(f"{w('pPr')}/{w('ind')}")
            lists[num.get(w("numId"))] = {
                "format": val(lvl.find(w("numFmt"))), "glyph": "U+%04X" % ord(val(lvl.find(w("lvlText"))) or " "),
                "glyph_font": styles.font(lvl.find(w("rPr"))),
                "indent_left_twips": int(val(ind, "left")), "hanging_twips": int(val(ind, "hanging")),
                "text_x_pt": round((int(mar.get(w("left"))) + int(val(ind, "left"))) / 20, 2),
                "glyph_x_pt": round((int(mar.get(w("left"))) + int(val(ind, "left")) - int(val(ind, "hanging"))) / 20, 2)}

    fonts: dict[str, int] = {}
    for el in [root] + [etree.fromstring(parts[p]) for p in ("word/header1.xml", "word/footer1.xml") if p in parts]:
        for p in el.iter(w("p")):
            for item in describe_runs(p, styles):
                if item["text"].strip():
                    key = f"{item['font']} {item['size_pt']:g}pt{' bold' if item['bold'] else ''}"
                    fonts[key] = fonts.get(key, 0) + 1

    def style_info(style_id: str) -> dict[str, Any]:
        style = styles.by_id.get(style_id)
        if style is None:
            return {}
        rpr = style.find(w("rPr"))
        return {"name": val(style.find(w("name"))), "basedOn": val(style.find(w("basedOn"))),
                **describe_ppr(style.find(w("pPr"))), "font": styles.font(rpr),
                "size_pt": int(val(rpr.find(w("sz")))) / 2 if rpr is not None and rpr.find(w("sz")) is not None else None,
                "bold": is_bold(rpr), "color": val(rpr.find(w("color"))) if rpr is not None else None,
                "underline": val(rpr.find(w("u"))) if rpr is not None else None}

    used_styles = sorted({p.get("style") for p in paragraphs if p.get("style")} | {"Normal", "Header", "Footer", "Hyperlink"})
    settings = etree.fromstring(parts["word/settings.xml"])
    compat = next((s.get(w("val")) for s in settings.iter(w("compatSetting")) if s.get(w("name")) == "compatibilityMode"), None)
    heading = paragraphs[next(i for i, p in enumerate(paragraphs) if p["kind"] == "heading")]
    rels = {r.get("Id"): r for r in etree.fromstring(parts["word/_rels/document.xml.rels"])}
    header_ref = sect.find(w("headerReference"))
    footer_ref = sect.find(w("footerReference"))

    return {
        "golden": {"file": "templates/" + golden_path().name, "sha256": hashlib.sha256(data).hexdigest(),
                   "note": "The DOCX is the visual authority. This file documents it and names content slots."},
        "page": {"size": "US Letter" if (pg.get(w("w")), pg.get(w("h"))) == ("12240", "15840") else "custom",
                 "width_twips": int(pg.get(w("w"))), "height_twips": int(pg.get(w("h"))),
                 "width_pt": twips_pt(pg.get(w("w"))), "height_pt": twips_pt(pg.get(w("h"))),
                 "orientation": pg.get(w("orient")) or "portrait",
                 "doc_grid_line_pitch_twips": int(val(sect.find(w("docGrid")), "linePitch") or 0)},
        "margins": {k: {"twips": int(mar.get(w(k))), "pt": twips_pt(mar.get(w(k)))}
                    for k in ("top", "right", "bottom", "left", "header", "footer", "gutter")},
        "text_width_pt": twips_pt(str(int(pg.get(w("w"))) - int(mar.get(w("left"))) - int(mar.get(w("right"))))),
        "doc_defaults": {"run": styles.effective(None, None),
                         "paragraph": describe_ppr(styles.defaults("pPr"))},
        "settings": {"compatibility_mode": compat, "default_tab_stop_twips": int(val(settings.find(w("defaultTabStop"))) or 0),
                     "auto_hyphenation": settings.find(w("autoHyphenation")) is not None},
        "styles": {s: style_info(s) for s in used_styles},
        "fonts_used": dict(sorted(fonts.items(), key=lambda kv: -kv[1])),
        "bullets": lists,
        "headings": {"style": heading.get("style"), "spacing": heading.get("spacing"), "runs": heading["runs"][:1],
                     "rule": "heading text and trailing tabs/spaces are underlined, drawing a rule to the right margin"},
        "section_separators": {"between_roles": [{"paragraph": i, "method": "underscore characters" if "_" in para_text(children[i])
                                                  else "underlined spaces and tabs", **describe_ppr(children[i].find(w("pPr")))}
                                                 for i in slots["separators"]]},
        "header": {"part": rels[header_ref.get(f"{{{R_NS}}}id")].get("Target") if header_ref is not None else None,
                   **_header_footer(parts["word/header1.xml"], parts.get("word/_rels/header1.xml.rels"), styles)},
        "footer": {"part": rels[footer_ref.get(f"{{{R_NS}}}id")].get("Target") if footer_ref is not None else None,
                   **_header_footer(parts["word/footer1.xml"], parts.get("word/_rels/footer1.xml.rels"), styles)},
        "hyperlink_style": style_info("Hyperlink"),
        "role_headers": [{k: r[k] for k in ("employment_id", "slot", "header", "text", "dates", "alignment", "runs")}
                         for r in slots["roles"]],
        "section_order": [s for s, _ in sorted(slots["headings"].items(), key=lambda kv: kv[1])],
        "slots": slots,
        "runs": {"summary": "first sentence bold (without its full stop), rest normal",
                 "experience": "bold lead clause up to the first comma or semicolon, rest normal",
                 "projects": "bold 'Name:', rest normal", "skills": "bold label, ': ' and items normal",
                 "lead": {"min_chars": leads[0] if leads else 20, "max_chars": leads[-1] if leads else 120,
                          "median_chars": int(statistics.median(leads)) if leads else 60}},
        "paragraphs": paragraphs,
        "locked_parts": {name: hashlib.sha256(parts[name]).hexdigest() for name in LOCKED_PARTS if name in parts},
        "section_properties_sha256": hashlib.sha256(canonical(sect).encode()).hexdigest(),
        "style_exemplars": exemplars,
        "checks": checks,
    }


@lru_cache(maxsize=4)
def _read(path: str, mtime: float) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def load_spec() -> dict[str, Any]:
    path = spec_path()
    if not path.is_file():
        raise FileNotFoundError(f"Resume template spec not found at {path}. Run: python -m app.services.career_compiler.docx_template")
    return _read(str(path), path.stat().st_mtime)


@lru_cache(maxsize=4)
def _golden(path: str, mtime: float) -> bytes:
    return Path(path).read_bytes()


def load_golden() -> bytes:
    path = golden_path()
    if not path.is_file():
        raise FileNotFoundError(f"Golden resume template not found at {path}.")
    return _golden(str(path), path.stat().st_mtime)


def template_digest(spec: dict[str, Any]) -> str:
    return spec["golden"]["sha256"][:16]


def write_spec(calibrate: bool = True) -> dict[str, Any]:
    from app.services.career_compiler.store import load_store
    store = load_store()
    data = golden_path().read_bytes()
    spec = inspect(data, store.employment, store.data.get("education") or [])
    if calibrate:
        from app.services.career_compiler.docx_render import calibrate as measure_golden
        spec["rendered"] = measure_golden(spec, data)
    spec_path().write_text(json.dumps(spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return spec


if __name__ == "__main__":
    import sys
    result = write_spec(calibrate="--no-word" not in sys.argv)
    print(f"Wrote {spec_path()}: {len(result['paragraphs'])} paragraphs, {len(result['slots']['roles'])} roles, "
          f"{len(result['checks'])} career.json checks"
          + (f", Word capacity {result['rendered']['capacity_lines']} lines" if "rendered" in result else ""))
