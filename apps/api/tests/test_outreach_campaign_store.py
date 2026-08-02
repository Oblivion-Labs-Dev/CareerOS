from __future__ import annotations

import json
from pathlib import Path

from app.services.outreach_campaign_store import load_campaigns, repair_campaign_file, save_campaigns


def _campaign(campaign_id: str, count: int = 2) -> dict[str, object]:
    return {
        "id": campaign_id,
        "label": f"Campaign {campaign_id}",
        "status": "completed",
        "summary": {"total": count, "sent": count, "failed": 0, "pending": 0, "skipped": 0},
        "results": [
            {"id": f"{campaign_id}-{index}", "email": f"person{index}@example.com", "status": "sent"}
            for index in range(count)
        ],
    }


def test_round_trip_uses_atomic_backup(tmp_path: Path) -> None:
    path = tmp_path / "campaigns.json"
    save_campaigns(path, [_campaign("one")])
    save_campaigns(path, [_campaign("two")])

    assert load_campaigns(path).campaigns[0]["id"] == "two"
    backups = list(tmp_path.glob("campaigns.json.bak-*"))
    assert len(backups) == 1
    assert json.loads(backups[0].read_text(encoding="utf-8"))[0]["id"] == "one"


def test_recovers_complete_campaigns_and_results_from_truncated_write(tmp_path: Path) -> None:
    first = _campaign("one")
    partial = json.dumps(_campaign("two", count=3), indent=2)
    truncated = "[\n" + json.dumps(first, indent=2) + ",\n" + partial.rsplit('"status": "sent"', 1)[0]
    path = tmp_path / "campaigns.json"
    path.write_text(truncated, encoding="utf-8")

    loaded = load_campaigns(path)

    assert loaded.recovered is True
    assert [campaign["id"] for campaign in loaded.campaigns] == ["one", "two"]
    assert len(loaded.campaigns[1]["results"]) == 2
    assert loaded.campaigns[1]["summary"]["total"] == 2
    assert loaded.discarded_incomplete_items == 1


def test_repair_keeps_exact_corrupt_source_as_backup(tmp_path: Path) -> None:
    path = tmp_path / "campaigns.json"
    original = '[{"id":"one","results":[]}, {"id":"broken","results":[{"id":"partial"'
    path.write_text(original, encoding="utf-8")

    backup = repair_campaign_file(path)

    assert backup is not None
    assert backup.read_text(encoding="utf-8") == original
    assert load_campaigns(path).recovered is False


def test_uses_latest_valid_backup_when_source_is_not_an_array(tmp_path: Path) -> None:
    path = tmp_path / "campaigns.json"
    path.write_text("not-json", encoding="utf-8")
    backup = tmp_path / "campaigns.json.bak-1"
    backup.write_text(json.dumps([_campaign("backup")]), encoding="utf-8")

    loaded = load_campaigns(path)

    assert loaded.recovered is True
    assert loaded.campaigns[0]["id"] == "backup"
