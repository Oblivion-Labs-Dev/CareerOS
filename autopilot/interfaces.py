"""Public contract for the autopilot service.

Browser automation, form filling, the application queue, submission tracking
and self-repair. Other services import ONLY from this module.
"""

from typing import Any, Protocol

from sqlalchemy.orm import Session


class IAutopilotService(Protocol):
    def list_applications(self, db: Session) -> list[dict[str, Any]]: ...
    async def enqueue(self, db: Session, job_id: str) -> dict: ...
    def get_queue_status(self, db: Session) -> dict: ...
