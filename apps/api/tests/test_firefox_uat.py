import json
import sqlite3
import pytest
import asyncio
from types import SimpleNamespace

from app.services.uat.firefox import BrowserConfig, TargetPolicy, proxy_from_url
from app.services.uat.database import ReviewAdapter
from app.services.uat.firefox import FirefoxUAT


def test_proxy_credentials_and_validation():
    proxy = proxy_from_url('http://user:p%40ss@127.0.0.1:8080')
    assert proxy == {'server': 'http://127.0.0.1:8080', 'username': 'user', 'password': 'p@ss'}
    with pytest.raises(ValueError):
        proxy_from_url('file:///secret')
    with pytest.raises(ValueError):
        BrowserConfig(engine='chromium')


def test_exact_origin_policy_rejects_lookalikes_and_live_commit():
    policy = TargetPolicy(('https://boards.greenhouse.io',))
    assert policy.allows('https://boards.greenhouse.io/example/jobs/1')
    assert not policy.allows('https://boards.greenhouse.io.evil.test/1')
    assert not policy.allows('http://boards.greenhouse.io/1')
    assert not policy.allows('https://user:password@boards.greenhouse.io/1')
    with pytest.raises(ValueError):
        TargetPolicy(('https://boards.greenhouse.io',), fixture=True)


def test_manual_review_snapshot_is_bounded_read_only_and_minimal(tmp_path):
    path = tmp_path / 'review.db'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE entities(id TEXT, entity_type TEXT, payload TEXT); CREATE TABLE kv_store(key TEXT,value TEXT);')
        db.execute('INSERT INTO kv_store VALUES (?,?)', ('profile', json.dumps({'firstName':'Test','email':'test@example.invalid','salaryExpectations':'private'})))
        for i, status in enumerate(['NEEDS_REVIEW','MANUAL_REVIEW','SUBMITTED']):
            db.execute('INSERT INTO entities VALUES (?,?,?)', (str(i),'aa_autopilot_job',json.dumps({'id':str(i),'jobId':str(i),'status':status,'applicationUrl':'https://jobs.lever.co/example/1'})))
    before = path.read_bytes()
    with ReviewAdapter('sqlite:///' + path.as_posix()) as adapter:
        rows = adapter.snapshot(limit=1)
        assert len(rows) == 1
        assert rows[0].profile == {'firstName':'Test','email':'test@example.invalid'}
        with pytest.raises(ValueError):
            adapter.snapshot(limit=11)
        with pytest.raises(Exception):
            adapter.connection.exec_driver_sql('DELETE FROM entities')
    assert before == path.read_bytes()


def test_live_submission_and_write_requests_are_blocked():
    browser = FirefoxUAT(BrowserConfig(), TargetPolicy(('https://jobs.lever.co',)))
    class Route:
        request = SimpleNamespace(method='POST', url='https://jobs.lever.co/apply', is_navigation_request=lambda:False)
        aborted = False
        async def abort(self): self.aborted = True
        async def continue_(self): raise AssertionError('Live write escaped the guard')
    async def run():
        route = Route()
        await browser._route(route)
        assert route.aborted
        with pytest.raises(PermissionError):
            await browser.safely_commit_form(None, None)
    asyncio.run(run())


def test_config_and_logs_never_expose_proxy_secret():
    assert 'secret' not in repr(BrowserConfig(proxy_url='http://user:secret@proxy.example:8080'))
    with pytest.raises(ValueError) as caught:
        proxy_from_url('http://user:secret@proxy.example:bad')
    assert 'secret' not in str(caught.value)
