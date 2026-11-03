"""Public contract for the profile service.

Other services import ONLY from this module — never from ``profile.service``
or ``profile.repository``. Extraction to a microservice means writing one
HTTP client that implements this Protocol and swapping the injection.
"""

from typing import Any, Protocol

from sqlalchemy.orm import Session


class IProfileService(Protocol):
    def get(self, db: Session) -> dict[str, Any]: ...
    def update(self, db: Session, patch: dict[str, Any]) -> dict[str, Any]: ...
