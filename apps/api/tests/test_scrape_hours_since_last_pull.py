import math
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock
import pytest
from app.routers.api import JobDiscoverScrapePayload, start_job_discover_scrape


@pytest.mark.anyio
async def test_scrape_defaults_to_hours_since_last_pulled():
    now = datetime.now(timezone.utc)
    # Simulate last pulled 36 hours ago
    last_pulled = (now - timedelta(hours=36, minutes=10)).isoformat()

    mock_snapshot = {"scrapedAt": last_pulled}
    with patch("app.services.job_discover.store.get_snapshot", return_value=mock_snapshot), \
         patch("app.services.job_discover.store.get_status", return_value={"lastScrapedAt": None}), \
         patch("app.services.job_discover.store.start_scrape_background", return_value={"success": True}) as mock_start:
        
        # Call with no hours provided (default None)
        res = await start_job_discover_scrape(JobDiscoverScrapePayload(mode="ats"))
        assert res.get("success") is True
        # 36h 10m rounds up to 37 + 1 buffer = 38
        assert res.get("hours") == 38
        assert res.get("lastPulledAt") == last_pulled
        mock_start.assert_called_once_with(hours=38, roles="", mode="ats")


@pytest.mark.anyio
async def test_scrape_preserves_explicit_hours():
    mock_snapshot = {"scrapedAt": (datetime.now(timezone.utc) - timedelta(hours=50)).isoformat()}
    with patch("app.services.job_discover.store.get_snapshot", return_value=mock_snapshot), \
         patch("app.services.job_discover.store.start_scrape_background", return_value={"success": True}) as mock_start:
        
        res = await start_job_discover_scrape(JobDiscoverScrapePayload(hours=12, mode="ats"))
        assert res.get("success") is True
        assert res.get("hours") == 12
        mock_start.assert_called_once_with(hours=12, roles="", mode="ats")


@pytest.mark.anyio
async def test_scrape_fallback_when_never_scraped():
    mock_snapshot = {"scrapedAt": None}
    with patch("app.services.job_discover.store.get_snapshot", return_value=mock_snapshot), \
         patch("app.services.job_discover.store.get_status", return_value={"lastScrapedAt": None}), \
         patch("app.services.job_discover.store.start_scrape_background", return_value={"success": True}) as mock_start:
        
        res = await start_job_discover_scrape(JobDiscoverScrapePayload(mode="ats"))
        assert res.get("success") is True
        assert res.get("hours") == 24
        mock_start.assert_called_once_with(hours=24, roles="", mode="ats")

