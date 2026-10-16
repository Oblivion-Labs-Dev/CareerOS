"""Unified Storage Service for CareerOS artifacts (tailored resumes, screenshots, documents).

Supports:
- Local filesystem storage (default for dev and single-tenant local operation)
- Supabase Storage / S3-compatible cloud bucket storage for production cloud deployments
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from app.config import settings

logger = logging.getLogger("career_os.storage")

_DATA_DIR = Path(__file__).resolve().parents[2] / "data" / "application_assistant"


class StorageService:
    def __init__(self):
        self.supabase_url = settings.supabase_url.rstrip("/") if settings.supabase_url else ""
        self.supabase_key = settings.supabase_service_role_key or settings.supabase_anon_key

    def is_cloud_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_key)

    def save_file(
        self,
        subfolder: str,
        filename: str,
        content: bytes,
        content_type: str = "application/pdf",
    ) -> str:
        """Save a file either to cloud bucket or local filesystem. Returns path or URL."""
        if self.is_cloud_enabled():
            import httpx

            bucket = subfolder.replace("_", "-")
            url = f"{self.supabase_url}/storage/v1/object/{bucket}/{filename}"
            headers = {
                "Authorization": f"Bearer {self.supabase_key}",
                "apikey": self.supabase_key,
                "Content-Type": content_type,
                "x-upsert": "true",
            }
            try:
                with httpx.Client(timeout=15.0) as client:
                    resp = client.post(url, headers=headers, content=content)
                    if resp.is_success:
                        return f"{self.supabase_url}/storage/v1/object/public/{bucket}/{filename}"
                    logger.warning("Cloud upload failed with status %d, falling back to local disk", resp.status_code)
            except Exception as e:
                logger.warning("Cloud storage exception: %s; falling back to local disk", e)

        # Local filesystem fallback
        dest_dir = _DATA_DIR / subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_path = dest_dir / filename
        dest_path.write_bytes(content)
        return str(dest_path)

    def get_file_path(self, subfolder: str, filename: str) -> Path | None:
        """Return local Path if file exists on disk."""
        target = (_DATA_DIR / subfolder / filename).resolve()
        if (_DATA_DIR / subfolder).resolve() in target.parents or target.parent == (_DATA_DIR / subfolder).resolve():
            if target.is_file():
                return target
        return None


storage_service = StorageService()
