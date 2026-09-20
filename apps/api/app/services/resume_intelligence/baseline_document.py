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
        rule_rights = [d["rect"].x1 for d in page.get_drawings() if
                       d["rect"].width > page.rect.width * .65 and d["rect"].height < 3
                       and d["rect"].x1 < page.rect.width - 5]
        lines = [l for b in page.get_text("dict")["blocks"] if b["type"] == 0
                 for l in b["lines"] if any(s["text"].strip() for s in l["spans"])]
        lines.sort(key=lambda l: (round(l["spans"][0]["origin"][1], 1), l["bbox"][0]))
        bullets = []
        # The SKILLS section is parsed into its own list rather than into
        # `bullets`. It has the same marker-plus-lines shape, so the same loop
        # reads it, but it is not evidence and must never be offered as a
        # replacement for an achievement: it is a list whose *order* can be
        # tailored while its contents stay fixed.
        skills = []
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
            if section not in ("EXPERIENCE", "FEATURED PROJECTS", "PROJECTS", "SKILLS"):
                continue
            if marker is not None and abs(line["spans"][0]["origin"][1] - marker["spans"][0]["origin"][1]) < 3:
                if section != "EXPERIENCE":
                    company, role = "", ""
                    group = f"{section}:{text.split(':')[0]}"
                target = skills if section == "SKILLS" else bullets
                prefix = "skills" if section == "SKILLS" else "baseline"
                current = {"id": f"{prefix}-{len(target)}", "company": company, "role": role,
                           "project": role if company else text.split(":")[0], "group": group,
                           "section": section, "lines": [], "marker": deepcopy(marker)}
                target.append(current)
                marker = None
            elif current is None or line["bbox"][0] < 65:
                continue
            elif abs(line["spans"][0]["origin"][0] - current["lines"][0]["spans"][0]["origin"][0]) > 2:
                # A continuation line sits at its bullet's own indent. The
                # centred footer of links under SKILLS does not, and without
                # this it was swallowed into the last skills group — which then
                # re-typeset "HackerRank | Publication | Medium | Substack | X"
                # as part of the skills list and lost its formatting.
                continue
            # Keep every run, including its original font, position and weight.
            current["lines"].append(deepcopy(line))
        if not bullets or any(not b["lines"] for b in bullets):
            raise ValueError("Could not safely identify baseline bullet slots; keep the approved PDF unchanged.")
        digest = hashlib.sha256(data).hexdigest()
        for b in bullets + skills:
            b["richText"] = [dict(s, bold=bool(s["flags"] & 16)) for l in b["lines"] for s in l["spans"]]
            b["text"] = " ".join("".join(s["text"] for s in l["spans"]).strip() for l in b["lines"])
            rect = pdf.Rect(b["lines"][0]["bbox"])
            for line in b["lines"][1:]:
                rect |= pdf.Rect(line["bbox"])
            b["rect"] = list(rect)
            siblings = skills if b["section"] == "SKILLS" else bullets
            b["right"] = min(page.rect.width, max(rule_rights or [line["bbox"][2] for other in siblings
                             if other["group"] == b["group"] for line in other["lines"]]))
            b["source"] = {"field": "approvedResume", "text": b["text"], "revision": digest, "baselineBulletId": b["id"]}
        for entry in skills:
            entry.update(_split_skills(entry))
        return {"revision": digest, "pageRect": list(page.rect), "bullets": bullets,
                "skills": [entry for entry in skills if entry.get("items")],
                "text": page.get_text(sort=True), "filename": path.name}


#: What separates one skill from the next on a SKILLS line. The approved PDF
#: uses the SymbolMT bullet; the middle dot and a plain bullet are accepted too
#: so a re-exported baseline does not silently stop parsing.
SKILL_SEPARATORS = "\uf0b7\u2022\u00b7"
_SKILL_SPLIT = re.compile(f"[{SKILL_SEPARATORS}]")


def _split_skills(entry: dict) -> dict:
    """Split one SKILLS line into its bold label and its individual skills.

    The line reads "**Cloud & Platform**: AWS - Azure - Kubernetes - ...". The
    label is the bold run and is fixed; everything after the colon is a list
    whose order is the only thing tailoring may change.
    """
    label_runs = []
    for run in entry["richText"]:
        if not run["bold"]:
            break
        label_runs.append(run)
    label = "".join(run["text"] for run in label_runs)
    body = entry["text"][len(label):]
    separator = next((c for c in SKILL_SEPARATORS if c in body), "")
    body = body.lstrip()
    if body.startswith(":"):
        body = body[1:]
    items = [item.strip() for item in _SKILL_SPLIT.split(body) if item.strip()]
    return {"label": label, "labelRuns": label_runs, "items": items, "separator": separator}


def skills_runs(entry: dict, items: list[str]) -> list[dict]:
    """Re-style a SKILLS line for a new ordering of the same items.

    Only the order changes: the label, the separator and every item are the
    approved ones, so this cannot introduce a skill the candidate has not
    claimed. The runs reuse the line's own styles, so the bold label stays
    bold and the body keeps its font.
    """
    body_style = next((run for run in entry["richText"] if not run["bold"] and run["text"].strip()), None)
    if body_style is None or not entry.get("labelRuns"):
        return []
    separator = entry.get("separator") or "\uf0b7"
    joined = f" {separator} ".join(items)
    return [*(dict(run) for run in entry["labelRuns"]), dict(body_style, text=f": {joined} ")]


def replacement_runs(text: str, slot: dict) -> list[dict]:
    """Style exact source text using the slot's bold-opening / normal-body pattern.

    Only formatting boundaries are assigned; not one claim character is edited.
    Explicit authored formatting can be carried by callers, but plain sources
    inherit the incumbent's opening length (ending at a word boundary).
    """
    runs = slot["richText"]
    if text == slot["text"]:
        return deepcopy(runs)
    normal = next((r for r in runs if not r["bold"] and r["text"].strip()), None)
    opening = []
    for run in runs:
        if not run["bold"]:
            break
        opening.append(run["text"])
    cut = 0
    if opening and normal:
        phrase = re.search(r"[,;:]", text)
        if phrase and 15 <= phrase.start() <= 125 and phrase.start() < len(text) - 5:
            cut = phrase.start()
        else:
            desired = min(len("".join(opening)), max(1, len(text) // 2))
            boundaries = [m.start() for m in re.finditer(r"\s+", text)]
            cut = min(boundaries, key=lambda n: abs(n-desired)) if boundaries else 0
    pieces = [(text[:cut], runs[0]), (text[cut:], normal or runs[0])] if cut else [(text, normal or runs[0])]
    return [dict(style, text=value) for value, style in pieces if value]


def _page_fonts(doc) -> dict:
    """The page's own embedded fonts, by the name its spans refer to."""
    fonts = {}
    for xref, _, _, name, *_ in doc[0].get_fonts():
        name = name.split("+")[-1]
        if name not in fonts:
            buffer = doc.extract_font(xref)[3]
            fonts[name] = pdf.Font(fontbuffer=buffer) if buffer else pdf.Font(fontname=name)
    return fonts


def group_slots(baseline: dict, slot: dict) -> list[dict]:
    """Every slot sharing this one's group, in document order.

    A group is one employer's block of bullets, one project, or one SKILLS
    line. Slots inside a group sit in a single run of lines, which is what
    makes reflow between them possible without moving anything else.
    """
    siblings = baseline["skills"] if slot.get("section") == "SKILLS" else baseline["bullets"]
    return [other for other in siblings if other["group"] == slot["group"]]


def _rows(slots: list[dict]) -> list[float]:
    """The baseline y of every text line these slots occupy, top to bottom."""
    return sorted(line["spans"][0]["origin"][1] for slot in slots for line in slot["lines"])


def reflow_layout(doc, block: list[dict], runs_by_id: dict[str, list[dict]]):
    """Lay a contiguous block of *changed* slots across their combined lines.

    `_replacement_layout` locks each bullet to its own baselines, so a
    replacement one word longer than the incumbent is refused even when the
    bullet next to it ends half a line short. The page has the room; the line
    boxes are frozen per bullet. This pools the lines belonging to the slots
    that are changing, so a longer bullet can borrow a line from a shorter
    sibling that is changing in the same breath.

    Two deliberate limits, both about not corrupting the page:

    * **Only changed slots are laid out.** Re-typesetting an unchanged bullet
      is unsafe: `font.text_length` does not reproduce the original tool's line
      breaking exactly, and measured on this resume one bullet in seven wraps a
      line earlier than the PDF did. Re-wrapping an untouched bullet could
      therefore silently push a line off the end of the group and drop text.
      Unchanged bullets keep their original pixels and are never redacted.
    * **Only a contiguous block.** Slots keep their order and their place, so
      text can only be redistributed between neighbours that are all changing;
      a bullet may never jump over an untouched one.

    The block's line count is fixed, so nothing below it moves and the page
    cannot grow.
    """
    fonts = _page_fonts(doc)
    grid = _rows(block)
    placed: dict[str, dict] = {}
    row = 0
    for slot in block:
        if row >= len(grid):
            return None
        entry: dict = {"text": [], "marker": None}
        marker = slot.get("marker")
        # A marker only has to move when its bullet no longer starts on the row
        # it started on. When it does move it has to be re-drawn, and this
        # page's bullet glyph (U+2022 in a subset of SymbolMT) has no outline in
        # the embedded font — re-drawing it produced a hollow box on a generated
        # resume. So a block that would move a marker is refused outright, and
        # one that leaves every marker where it is keeps the original pixels.
        if marker and marker["spans"]:
            span = marker["spans"][0]
            if abs(grid[row] - slot["lines"][0]["spans"][0]["origin"][1]) > .1:
                font = fonts.get(span["font"])
                if font is None or any(not font.has_glyph(ord(c)) for c in span["text"] if not c.isspace()):
                    return None
                entry["marker"] = (span["origin"][0], grid[row], span["text"], font, span)
        x0 = slot["lines"][0]["spans"][0]["origin"][0]
        x = x0
        for run in runs_by_id.get(slot["id"], slot["richText"]):
            font = fonts.get(run["font"])
            if font is None or any(not font.has_glyph(ord(c)) for c in run["text"] if not c.isspace()):
                return None
            for token in re.findall(r"\s+|\S+", run["text"]):
                width = font.text_length(token, fontsize=run["size"])
                if x + width > slot["right"] + .01:
                    row, x = row + 1, x0
                    if row >= len(grid):
                        return None
                    if token.isspace():
                        continue
                if x + width > slot["right"] + .01:
                    return None
                entry["text"].append((x, grid[row], token, font, run))
                x += width
        placed[slot["id"]] = entry
        row += 1
    return placed


def contiguous_block(baseline: dict, slot: dict, changed_ids: set[str]) -> list[dict]:
    """`slot` plus the changed slots immediately around it, in document order."""
    siblings = group_slots(baseline, slot)
    index = next((i for i, other in enumerate(siblings) if other["id"] == slot["id"]), None)
    if index is None:
        return [slot]
    wanted = set(changed_ids) | {slot["id"]}
    first = index
    while first > 0 and siblings[first - 1]["id"] in wanted:
        first -= 1
    last = index
    while last + 1 < len(siblings) and siblings[last + 1]["id"] in wanted:
        last += 1
    return siblings[first:last + 1]


def reflow_fits(baseline: dict, slot: dict, runs: list[dict],
                runs_by_id: dict[str, list[dict]] | None = None, path: Path | None = None) -> bool:
    """Whether `runs` fit once the changed slots around `slot` pool their lines."""
    combined = dict(runs_by_id or {})
    combined[slot["id"]] = runs
    block = contiguous_block(baseline, slot, set(combined))
    if len(block) < 2:
        return False  # Nothing to borrow from; the per-slot check already ruled.
    with pdf.open(path or approved_path()) as doc:
        return reflow_layout(doc, block, combined) is not None


def pack_to_fit(entry: dict, ordered: list[str], build_runs, fit_check) -> list[str] | None:
    """The most relevant ordering of the same items that still fits the line.

    A SKILLS line is a permutation, so it has the same characters either way —
    but not the same line breaks, and a long item pulled to the front can push
    the wrap and cost a whole line the approved layout does not have. Measured
    on this resume, that is what stopped the twenty-item "Cloud & Platform"
    line from being re-ordered for a security posting.

    Rather than give up and keep the original order, the relevance order is
    kept and repaired: walk it, and whenever the result does not fit, move the
    longest item that has not been tried yet to the back. The front of the line
    — the part a keyword screen reads — keeps the posting's own vocabulary,
    which is the whole point of re-ordering it.
    """
    candidate = list(ordered)
    for _ in range(len(candidate)):
        runs = build_runs(entry, candidate)
        if runs and fit_check(entry, runs):
            return candidate
        # Demote the longest item still ahead of the ones already demoted.
        movable = candidate[:len(candidate)]
        longest = max(range(len(movable)), key=lambda i: (len(movable[i]), -i))
        candidate = [*candidate[:longest], *candidate[longest + 1:], candidate[longest]]
    return None


def _replacement_layout(doc, slot: dict, runs: list[dict]):
    """Exact embedded fonts and fixed line baselines; no font shrinking or reflow outside slot."""
    fonts = _page_fonts(doc)
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


def _draw(page, layout) -> None:
    """Place one laid-out run sequence back on the page in its own colour."""
    for x, y, text, font, run in layout:
        writer = pdf.TextWriter(page.rect)
        writer.append((x, y), text, font=font, fontsize=run["size"])
        color = tuple(((run["color"] >> shift) & 255) / 255 for shift in (16, 8, 0))
        writer.write_text(page, color=color)


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
    if sorted(item.get("baselineBulletId", "") for item in items) != sorted(s["id"] for s in slots):
        raise ValueError("Each baseline bullet slot must occur exactly once.")
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
    # Skills lines are permutations of the approved list, verified here as well
    # as in `validate`, because this is the last point before the bytes go out.
    approved_skills = {entry["id"]: entry for entry in baseline.get("skills") or []}
    skill_changes = []
    for entry in result.get("skillsOrder") or []:
        if entry.get("decision") != "REORDER":
            continue
        source = approved_skills.get(entry.get("id"))
        if source is None or sorted(entry.get("items") or []) != sorted(source["items"]):
            raise ValueError("A skills line must contain exactly the approved skills.")
        if entry.get("richText") != skills_runs(source, entry["items"]):
            raise ValueError("A skills line must inherit approved typography.")
        skill_changes.append((source, entry))

    changes = [(slot, item) for slot, item in zip(slots, items) if item["decision"] != "KEEP"]
    if not changes and not skill_changes:
        return path.read_bytes()
    with pdf.open(path) as original, pdf.open(path) as output:
        page = output[0]
        layouts = {}
        markers = {}
        # Bullets accepted only because the slots changing around them pooled
        # their lines are laid out as a block; everything else stays per-slot,
        # so a resume that already fitted renders exactly as it did before.
        replaced_runs = {slot["id"]: item["richText"] for slot, item in changes if item["decision"] == "REPLACE"}
        reflow_blocks = []
        for slot, item in changes:
            if item["decision"] == "REPLACE" and item.get("reflowed"):
                block = contiguous_block(baseline, slot, set(replaced_runs))
                if not any(other["id"] in {s["id"] for s in block} for other in sum(reflow_blocks, [])):
                    reflow_blocks.append(block)
        reflowed_ids = {other["id"] for block in reflow_blocks for other in block}
        for block in reflow_blocks:
            placed = reflow_layout(original, block, replaced_runs)
            if placed is None:
                raise ValueError("Reflowed bullets cannot fit the approved typography; regenerate.")
            for slot_id, entry in placed.items():
                layouts[slot_id] = entry["text"]
                if entry["marker"]:
                    markers[slot_id] = entry["marker"]
            for other in block:
                page.add_redact_annot(pdf.Rect(other["rect"]), fill=False)
                if other["marker"] and other["id"] in markers:
                    page.add_redact_annot(pdf.Rect(other["marker"]["bbox"]), fill=False)
        for slot, item in changes:
            if item["decision"] == "REPLACE" and slot["id"] not in reflowed_ids:
                layout = _replacement_layout(original, slot, item["richText"])
                if layout is None:
                    raise ValueError("Replacement cannot fit the approved typography; regenerate.")
                layouts[slot["id"]] = layout
            if slot["id"] not in reflowed_ids:
                page.add_redact_annot(pdf.Rect(slot["rect"]), fill=False)
        for source, entry in skill_changes:
            layout = _replacement_layout(original, source, entry["richText"])
            if layout is None:
                raise ValueError("A re-ordered skills line cannot fit the approved typography; regenerate.")
            layouts[source["id"]] = layout
            page.add_redact_annot(pdf.Rect(source["rect"]), fill=False)
        page.apply_redactions(images=0, graphics=0)
        for x, y, text, font, span in markers.values():
            writer = pdf.TextWriter(page.rect)
            writer.append((x, y), text, font=font, fontsize=span["size"])
            color = tuple(((span["color"] >> shift) & 255) / 255 for shift in (16, 8, 0))
            writer.write_text(page, color=color)
        for slot, item in changes:
            if slot["id"] in reflowed_ids:
                _draw(page, layouts[slot["id"]])
                continue
            if item["decision"] == "REORDER":
                source = next(b for b in slots if b["id"] == item["baselineBulletId"])
                # Isolate source text before placing it: clipping alone leaves
                # invisible full-page text in ATS extraction.
                with pdf.open(path) as isolated:
                    crop = pdf.Rect(source["rect"])
                    width, height = isolated[0].rect.width, isolated[0].rect.height
                    for rect in (pdf.Rect(0, 0, width, crop.y0), pdf.Rect(0, crop.y1, width, height),
                                 pdf.Rect(0, crop.y0, crop.x0, crop.y1), pdf.Rect(crop.x1, crop.y0, width, crop.y1)):
                        isolated[0].add_redact_annot(rect, fill=False)
                    isolated[0].apply_redactions(images=0, graphics=0)
                    dest = pdf.Rect(crop)
                    dest.y0 += slot["rect"][1] - crop.y0
                    dest.y1 = dest.y0 + crop.height
                    page.show_pdf_page(dest, isolated, 0, clip=crop)
            else:
                _draw(page, layouts[slot["id"]])
        for source, _entry in skill_changes:
            _draw(page, layouts[source["id"]])
        data = output.tobytes(garbage=4, deflate=True)
    with pdf.open(stream=data, filetype="pdf") as check:
        if len(check) != 1:
            raise ValueError("Tailored PDF must remain one page.")
    return data
