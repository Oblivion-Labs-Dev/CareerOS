"""Indeed Hiring Lab AI posting share (ai-tracker dataset)."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_CANDIDATES = [
    Path(__file__).resolve().parents[2] / "data" / "market" / "AI_posting.csv",
    Path(r"D:\1 - Projects\Projects\aijobsearch\ai-tracker\AI_posting.csv"),
]


def _resolve_csv_path() -> Path | None:
    for candidate in DATA_CANDIDATES:
        if candidate.is_file():
            return candidate
    return None


@lru_cache(maxsize=1)
def load_ai_posting_series(*, country: str = "US") -> list[dict[str, Any]]:
    path = _resolve_csv_path()
    if not path:
        return []
    country = country.upper()
    rows: list[dict[str, Any]] = []
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (row.get("jobcountry") or "").upper() != country:
                continue
            date = row.get("date") or ""
            share = row.get("AI_share_postings")
            if not date or share is None:
                continue
            try:
                rows.append({"date": date, "share": round(float(share), 2)})
            except ValueError:
                continue
    rows.sort(key=lambda item: item["date"])
    return rows


def market_trends_summary(*, country: str = "US") -> dict[str, Any]:
    series = load_ai_posting_series(country=country)
    if not series:
        return {
            "available": False,
            "country": country,
            "series": [],
            "latestShare": None,
            "changeSince2019": None,
            "source": "Indeed Hiring Lab AI Tracker (CC BY 4.0)",
        }
    latest = series[-1]
    first = series[0]
    change = round(latest["share"] - first["share"], 2)
    # Downsample for chart readability (~52 weekly-ish points max)
    step = max(1, len(series) // 52)
    sampled = series[::step]
    if sampled[-1]["date"] != latest["date"]:
        sampled.append(latest)
    return {
        "available": True,
        "country": country,
        "series": sampled,
        "latestShare": latest["share"],
        "latestDate": latest["date"],
        "changeSince2019": change,
        "source": "Indeed Hiring Lab AI Tracker (CC BY 4.0)",
    }
