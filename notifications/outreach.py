"""Resilient persistence for recruiter outreach campaign history."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.safe_write import atomic_write


@dataclass(frozen=True)
class CampaignLoadResult:
    campaigns: list[dict[str, Any]]
    recovered: bool = False
    warning: str | None = None
    discarded_incomplete_items: int = 0


def _validated_campaigns(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError("Campaign history must be a JSON array of objects")
    return value


def _recalculate_summary(campaign: dict[str, Any]) -> None:
    results = campaign.get("results")
    if not isinstance(results, list):
        results = []
        campaign["results"] = results
    campaign["summary"] = {
        "total": len(results),
        "sent": sum(1 for result in results if result.get("status") == "sent"),
        "failed": sum(1 for result in results if result.get("status") == "failed"),
        "pending": sum(1 for result in results if result.get("status") in {"pending", "retrying"}),
        "skipped": sum(1 for result in results if result.get("status") == "skipped"),
    }


def _recover_partial_campaign(fragment: str, decoder: json.JSONDecoder) -> dict[str, Any] | None:
    results_key = fragment.find('"results"')
    if results_key < 0:
        return None
    array_start = fragment.find("[", results_key)
    if array_start < 0:
        return None

    try:
        campaign = decoder.decode(fragment[:results_key] + '"results": []}')
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(campaign, dict):
        return None

    results: list[dict[str, Any]] = []
    cursor = array_start + 1
    while cursor < len(fragment):
        while cursor < len(fragment) and (fragment[cursor].isspace() or fragment[cursor] == ","):
            cursor += 1
        if cursor >= len(fragment) or fragment[cursor] == "]":
            break
        try:
            item, cursor = decoder.raw_decode(fragment, cursor)
        except json.JSONDecodeError:
            break
        if not isinstance(item, dict):
            break
        results.append(item)

    campaign["results"] = results
    _recalculate_summary(campaign)
    return campaign


def _recover_truncated_array(content: str) -> CampaignLoadResult | None:
    start = 0
    while start < len(content) and content[start].isspace():
        start += 1
    if start >= len(content) or content[start] != "[":
        return None

    decoder = json.JSONDecoder()
    campaigns: list[dict[str, Any]] = []
    cursor = start + 1
    while cursor < len(content):
        while cursor < len(content) and (content[cursor].isspace() or content[cursor] == ","):
            cursor += 1
        if cursor >= len(content) or content[cursor] == "]":
            break
        try:
            item, cursor = decoder.raw_decode(content, cursor)
        except json.JSONDecodeError:
            partial = _recover_partial_campaign(content[cursor:], decoder)
            if partial is not None:
                campaigns.append(partial)
            break
        if not isinstance(item, dict):
            return None
        campaigns.append(item)

    if not campaigns:
        return None
    return CampaignLoadResult(
        campaigns=campaigns,
        recovered=True,
        warning="The campaign file ended during a write; complete campaigns and results were recovered.",
        discarded_incomplete_items=1,
    )


def load_campaigns(path: Path) -> CampaignLoadResult:
    if not path.exists():
        return CampaignLoadResult(campaigns=[])
    content = path.read_text(encoding="utf-8")
    try:
        return CampaignLoadResult(campaigns=_validated_campaigns(json.loads(content)))
    except (json.JSONDecodeError, ValueError):
        recovered = _recover_truncated_array(content)
        if recovered is not None:
            return recovered

    backups = sorted(
        path.parent.glob(f"{path.name}.bak-*"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for backup in backups:
        try:
            campaigns = _validated_campaigns(json.loads(backup.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        return CampaignLoadResult(
            campaigns=campaigns,
            recovered=True,
            warning="The campaign file was unreadable; the newest valid backup was loaded.",
        )
    raise ValueError(f"No recoverable recruiter outreach history was found at {path}")


def save_campaigns(path: Path, campaigns: list[dict[str, Any]]) -> Path | None:
    validated = _validated_campaigns(campaigns)
    return atomic_write(path, json.dumps(validated, indent=2), backup=True)


def repair_campaign_file(path: Path, result: CampaignLoadResult | None = None) -> Path | None:
    loaded = result or load_campaigns(path)
    if not loaded.recovered:
        return None
    return save_campaigns(path, loaded.campaigns)
