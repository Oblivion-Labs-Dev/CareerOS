"""Shared FastAPI dependencies.

``db_session`` yields a request-scoped SQLAlchemy session using the shared
``session_scope``. It lives here (not in any one service's router) because
every service's router needs the same per-request session dependency.
"""

from collections.abc import Generator

from sqlalchemy.orm import Session

from shared.db import session_scope


def db_session() -> Generator[Session, None, None]:
    with session_scope() as db:
        yield db
