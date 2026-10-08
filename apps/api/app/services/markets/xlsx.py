"""Minimal .xlsx reader on the standard library.

Seeds are plain tables; openpyxl/pandas are not dependencies of the API, and a
zip of XML is all an xlsx is.
"""

from __future__ import annotations

import posixpath
import re
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

_NS = {
    "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
_T = "{%s}t" % _NS["m"]


def _sheet_path(target: str) -> str:
    # Targets are relative to xl/ ("worksheets/sheet1.xml") or absolute ("/xl/worksheets/sheet1.xml").
    if target.startswith("/"):
        return target.lstrip("/")
    return posixpath.normpath(posixpath.join("xl", target))


def read_workbook(path: str | Path) -> dict[str, list[dict[str, str]]]:
    """Every sheet as a list of rows; each row maps column letter -> text."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            for item in ET.fromstring(archive.read("xl/sharedStrings.xml")).findall("m:si", _NS):
                shared.append("".join(t.text or "" for t in item.iter(_T)))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {rel.get("Id"): rel.get("Target") or "" for rel in rels}
        sheets: dict[str, list[dict[str, str]]] = {}
        sheet_list = workbook.find("m:sheets", _NS)
        for sheet in sheet_list if sheet_list is not None else []:
            rel_id = sheet.get("{%s}id" % _NS["r"])
            xml = ET.fromstring(archive.read(_sheet_path(targets.get(rel_id, ""))))
            rows: list[dict[str, str]] = []
            for row in xml.iter("{%s}row" % _NS["m"]):
                values: dict[str, str] = {}
                for cell in row.findall("m:c", _NS):
                    column = re.match(r"[A-Z]+", cell.get("r") or "")
                    if not column:
                        continue
                    kind = cell.get("t")
                    value = cell.find("m:v", _NS)
                    if kind == "s" and value is not None and value.text is not None:
                        text = shared[int(value.text)]
                    elif kind == "inlineStr":
                        text = "".join(t.text or "" for t in cell.iter(_T))
                    elif value is not None and value.text is not None:
                        text = value.text
                    else:
                        continue
                    values[column.group()] = text.strip()
                if values:
                    values["_r"] = row.get("r") or ""
                rows.append(values)
            sheets[sheet.get("name") or f"Sheet{len(sheets) + 1}"] = rows
        return sheets


def table(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    """Rows keyed by header text, with the sheet row number in '_row'."""
    if not rows:
        return []
    header = {col: name for col, name in rows[0].items() if col != "_r"}
    out = []
    for row in rows[1:]:
        cells = {col: value for col, value in row.items() if col != "_r"}
        if not any(cells.values()):
            continue
        record = {header.get(col, col): value for col, value in cells.items()}
        record["_row"] = row.get("_r", "")
        out.append(record)
    return out
