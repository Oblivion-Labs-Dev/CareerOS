"""Public contract for the jobs service.

Other services import ONLY from this module. Extraction to a microservice means
writing one HTTP client that implements this Protocol and swapping the
injection.
"""

from typing import Any, Protocol

from sqlalchemy.orm import Session


class IJobService(Protocol):
    async def trigger_scrape(self) -> dict: ...
    def get_status(self, db: Session) -> dict: ...
    def list_discovered(self, db: Session, filters: dict[str, Any]) -> dict: ...
    def get_job(self, db: Session, job_id: str) -> dict: ...
