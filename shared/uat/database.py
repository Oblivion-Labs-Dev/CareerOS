"""Read-only snapshots of CareerOS's real entity/KV schema, without store startup hooks."""
from dataclasses import dataclass, field
import json
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

CONTACT_KEYS = ('firstName', 'lastName', 'fullName', 'email', 'phone', 'city',
                'state', 'country', 'location', 'linkedin', 'github', 'portfolio')


@dataclass(frozen=True)
class ReviewCase:
    job_id: str
    url: str
    status: str
    profile: dict = field(repr=False)


class ReviewAdapter:
    def __init__(self, database_url: str):
        url = make_url(database_url)
        if url.get_backend_name() == 'sqlite':
            path = Path(url.database or '').resolve(strict=True)
            self.engine = create_engine('sqlite:///file:' + path.as_posix() + '?mode=ro&uri=true', poolclass=NullPool)
        elif url.get_backend_name() == 'postgresql':
            self.engine = create_engine(url, poolclass=NullPool, connect_args={'connect_timeout': 10})
        else:
            raise ValueError('UAT supports SQLite and PostgreSQL read-only snapshots.')

    def __enter__(self):
        self.connection = self.engine.connect()
        if self.engine.dialect.name == 'sqlite':
            self.connection.exec_driver_sql('PRAGMA query_only=ON')
            self.connection.exec_driver_sql('PRAGMA busy_timeout=5000')
        else:
            self.connection.exec_driver_sql('SET TRANSACTION READ ONLY')
            self.connection.exec_driver_sql("SET LOCAL statement_timeout='5s'")
        return self

    def __exit__(self, *_):
        self.connection.rollback()
        self.connection.close()
        self.engine.dispose()

    def snapshot(self, limit=3):
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 10:
            raise ValueError('Review sample must contain 1–10 cases.')
        def decode(value):
            return json.loads(value) if isinstance(value, str) else value or {}
        raw = self.connection.execute(text('SELECT value FROM kv_store WHERE key=:key'), {'key': 'profile'}).scalar()
        profile = {k: v for k, v in decode(raw).items() if k in CONTACT_KEYS and isinstance(v, str) and v.strip()}
        status = "json_extract(payload, '$.status')" if self.engine.dialect.name == 'sqlite' else "payload->>'status'"
        rows = self.connection.execute(text(f'SELECT payload FROM entities WHERE entity_type=:type AND {status} IN (:review,:manual) ORDER BY id LIMIT :limit'),
                                       {'type': 'aa_autopilot_job', 'review': 'NEEDS_REVIEW', 'manual': 'MANUAL_REVIEW', 'limit': limit})
        cases = []
        for row in rows:
            job = decode(row[0])
            cases.append(ReviewCase(str(job.get('jobId') or job['id']), str(job.get('applicationUrl') or ''), job['status'], dict(profile)))
        return cases

