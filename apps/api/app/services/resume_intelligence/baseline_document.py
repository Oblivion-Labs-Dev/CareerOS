"""Approved PDF as an immutable layout, with structured, positioned text runs.

Unsupported layouts fail closed. No PDF path supplied in an export payload is
ever opened: the server's configured approved file is the only authority.
"""
from __future__ import annotations

import hashlib
import os
import re
from copy import deepcopy
from pathlib import Path

import pymupdf as pdf


def approved_path() -> Path:
    return Path(os.environ.get("CAREEROS_APPROVED_RESUME_PATH") or
                Path(__file__).resolve().parents[3] / "data" / "approved-resume.pdf")


def load_baseline(path: Path | None = None) -> dict:
    path = path or approved_path()
    if not path.is_file():
        raise ValueError("Configure an approved baseline PDF before tailoring; rebuilding is disabled.")
    data = path.read_bytes()
    with pdf.open(stream=data, filetype="pdf") as doc:
        if len(doc) != 1 or doc[0].rotation:
            raise ValueError("The approved baseline must be one unrotated page.")
        page = doc[0]
        lines = [l for b in page.get_text("dict")["blocks"] if b["type"] == 0
                 for l in b["lines"] if any(s["text"].strip() for s in l["spans"])]
        lines.sort(key=lambda l: (round(l["spans"][0]["origin"][1], 1), l["bbox"][0]))
        bullets = []
        section, company, role, group = "", "", "", ""
        current = None
        marker = None
        for line in lines:
            text = "".join(s["text"] for s in line["spans"]).strip()
            heading = text.rstrip("_ ")
            if heading in ("PROFESSIONAL SUMMARY", "EXPERIENCE", "EDUCATION", "FEATURED PROJECTS", "PROJECTS", "SKILLS"):
                section, current, marker = heading, None, None
                continue
            if section == "EXPERIENCE" and "|" in text and line["bbox"][0] < 50:
                parts = text.split("|")
                role, company = parts[0].strip(), parts[1].strip()
                group = f"{section}:{company}:{role}:{len(bullets)}"
                current, marker = None, None
                continue
            is_marker = text in ("•", "�", "·", "\uf0b7") and line["bbox"][0] < 70
            if is_marker:
                marker, current = line, None
                continue
            if section not in ("EXPERIENCE", "FEATURED PROJECTS", "PROJECTS"):
                continue
            if marker is not None and abs(line["spans"][0]["origin"][1] - marker["spans"][0]["origin"][1]) < 3:
                if section != "EXPERIENCE":
                    company, role = "", ""
                    group = f"{section}:{text.split(':')[0]}"
                current = {"id": f"baseline-{len(bullets)}", "company": company, "role": role,
                           "project": role if company else text.split(":")[0], "group": group,
                           "section": section, "lines": [], "marker": deepcopy(marker)}
                bullets.append(current)
                marker = None
            elif current is None or line["bbox"][0] < 65:
                continue
            # Keep every run, including its original font, position and weight.
            current["lines"].append(deepcopy(line))
        if not bullets or any(not b["lines"] for b in bullets):
            raise ValueError("Could not safely identify baseline bullet slots; keep the approved PDF unchanged.")
        digest = hashlib.sha256(data).hexdigest()
        for b in bullets:
            b["richText"] = [dict(s, bold=bool(s["flags"] & 16)) for l in b["lines"] for s in l["spans"]]
            b["text"] = " ".join("".join(s["text"] for s in l["spans"]).strip() for l in b["lines"])
            rect = pdf.Rect(b["lines"][0]["bbox"])
            for line in b["lines"][1:]:
                rect |= pdf.Rect(line["bbox"])
            b["rect"] = list(rect)
            b["right"] = page.rect.width - 36
            b["source"] = {"field": "approvedResume", "text": b["text"], "revision": digest, "baselineBulletId": b["id"]}
        return {"revision": digest, "pageRect": list(page.rect), "bullets": bullets,
                "text": page.get_text(sort=True), "filename": path.name}


def replacement_runs(text: str, slot: dict) -> list[dict]:
    """Style exact source text using the slot's bold-opening / normal-body pattern.

    Only formatting boundaries are assigned; not one claim character is edited.
    Explicit authored formatting can be carried by callers, but plain sources
    inherit the incumbent's opening length (ending at a word boundary).
    """
    runs = slot["richText"]
    normal = next((r for r in runs if not r["bold"] and r["text"].strip()), None)
    opening = []
    for run in runs:
        if not run["bold"]:
            break
        opening.append(run["text"])
    cut = 0
    if opening and normal:
        desired = min(len("".join(opening)), max(1, len(text) // 2))
        boundaries = [m.start() for m in re.finditer(r"\s+", text) if m.start() <= desired]
        cut = boundaries[-1] if boundaries else 0
    pieces = [(text[:cut], runs[0]), (text[cut:], normal or runs[0])] if cut else [(text, normal or runs[0])]
    return [dict(style, text=value) for value, style in pieces if value]


def _replacement_layout(doc, slot: dict, runs: list[dict]):
    """Exact embedded fonts and fixed line baselines; no font shrinking or reflow outside slot."""
    fonts = {}
    for xref, _, _, name, *_ in doc[0].get_fonts():
        name = name.split("+")[-1]
        if name not in fonts:
            buffer = doc.extract_font(xref)[3]
            fonts[name] = pdf.Font(fontbuffer=buffer) if buffer else pdf.Font(fontname=name)
    x0 = slot["lines"][0]["spans"][0]["origin"][0]
    baselines = [l["spans"][0]["origin"][1] for l in slot["lines"]]
    row, x, output = 0, x0, []
    for run in runs:
        font = fonts.get(run["font"])
        if font is None or any(not font.has_glyph(ord(c)) for c in run["text"] if not c.isspace()):
            return None
        for token in re.findall(r"\s+|\S+", run["text"]):
            width = font.text_length(token, fontsize=run["size"])
            if x + width > slot["right"] + .01:
                row, x = row + 1, x0
                if token.isspace():
                    continue
            if row >= len(baselines) or x + width > slot["right"] + .01:
                return None
            output.append((x, baselines[row], token, font, run))
            x += width
    return output


def fits(slot: dict, runs: list[dict], path: Path | None = None) -> bool:
    with pdf.open(path or approved_path()) as doc:
        return _replacement_layout(doc, slot, runs) is not None


def render_baseline(result: dict, path: Path | None = None) -> bytes:
    path = path or approved_path()
    baseline = load_baseline(path)
    if baseline["revision"] != result.get("baselineRevision"):
        raise ValueError("Approved resume changed; regenerate before export.")
    slots = baseline["bullets"]
    items = result.get("resumeBullets") or []
    if len(items) != len(slots):
        raise ValueError("Baseline bullet counts must be preserved.")
    for slot, item in zip(slots, items):
        source = next((s for s in slots if s["id"] == item.get("baselineBulletId")), None)
        if source is None or source["group"] != slot["group"]:
            raise ValueError("A bullet cannot move across roles or projects.")
        if item.get("decision") in ("KEEP", "REORDER"):
            if item.get("richText") != source["richText"] or item.get("optimizedBullet") != source["text"]:
                raise ValueError("Baseline rich text must remain identical.")
            if item["decision"] == "KEEP" and source["id"] != slot["id"]:
                raise ValueError("A kept bullet must remain in its original slot.")
        elif item.get("decision") == "REPLACE":
            if item.get("richText") != replacement_runs(item["optimizedBullet"], slot):
                raise ValueError("Replacement must inherit approved slot typography.")
            if item.get("source", {}).get("text") != item["optimizedBullet"]:
                raise ValueError("Replacement must be exact source text.")
        else:
            raise ValueError("Unknown tailoring decision.")
    changes = [(slot, item) for slot, item in zip(slots, items) if item["decision"] != "KEEP"]
    if not changes:
        return path.read_bytes()
    with pdf.open(path) as original, pdf.open(path) as output:
        page = output[0]
        layouts = {}
        for slot, item in changes:
            if item["decision"] == "REPLACE":
                layout = _replacement_layout(original, slot, item["richText"])
                if layout is None:
                    raise ValueError("Replacement cannot fit the approved typography; regenerate.")
                layouts[slot["id"]] = layout
            page.add_redact_annot(pdf.Rect(slot["rect"]), fill=False)
        page.apply_redactions(images=0, graphics=0)
        for slot, item in changes:
            if item["decision"] == "REORDER":
                source = next(b for b in slots if b["id"] == item["baselineBulletId"])
                # Isolate source text before placing it: clipping alone leaves
                # invisible full-page text in ATS extraction.
                with pdf.open(path) as isolated:
                    crop = pdf.Rect(source["rect"])
                    for rect in (pdf.Rect(0, 0, 612, crop.y0), pdf.Rect(0, crop.y1, 612, 792),
                                 pdf.Rect(0, crop.y0, crop.x0, crop.y1), pdf.Rect(crop.x1, crop.y0, 612, crop.y1)):
                        isolated[0].add_redact_annot(rect, fill=False)
                    isolated[0].apply_redactions(images=0, graphics=0)
                    dest = pdf.Rect(crop)
                    dest.y0 += slot["rect"][1] - crop.y0
                    dest.y1 = dest.y0 + crop.height
                    page.show_pdf_page(dest, isolated, 0, clip=crop)
            else:
                for x, y, text, font, run in layouts[slot["id"]]:
                    writer = pdf.TextWriter(page.rect)
                    writer.append((x, y), text, font=font, fontsize=run["size"])
                    color = tuple(((run["color"] >> shift) & 255) / 255 for shift in (16, 8, 0))
                    writer.write_text(page, color=color)
        data = output.tobytes(garbage=4, deflate=True)
    with pdf.open(stream=data, filetype="pdf") as check:
        if len(check) != 1:
            raise ValueError("Tailored PDF must remain one page.")
    return data
