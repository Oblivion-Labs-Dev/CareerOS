"""The ~50 MB discovery snapshot is parsed once, not on every request."""

import json
import os

from app.services.job_discover import store


def test_snapshot_is_parsed_once_and_refreshed_by_a_write(monkeypatch, tmp_path):
    snap_file = tmp_path / "jobs_snapshot.json"
    kv: dict = {}
    reads = {"kv": 0, "file": 0}

    def fake_get_kv(_db, key):
        if key == store.KV_KEY:
            reads["kv"] += 1
        return kv.get(key)

    real_read = store._read_snapshot_file

    def counting_read():
        reads["file"] += 1
        return real_read()

    monkeypatch.setattr(store, "SNAPSHOT_FILE", snap_file)
    monkeypatch.setattr(store, "DATA_DIR", tmp_path)
    monkeypatch.setattr(store, "get_kv", fake_get_kv)
    monkeypatch.setattr(store, "set_kv", lambda _db, key, value: kv.__setitem__(key, value))
    monkeypatch.setattr(store, "_read_snapshot_file", counting_read)
    monkeypatch.setattr(store, "_prune_stale_jobs", lambda jobs: jobs)
    monkeypatch.setattr(store, "_snapshot_cache", None)

    class DB:
        def commit(self):
            pass

    db = DB()
    store._persist_snapshot(db, {"jobs": [{"id": "a"}]})
    reads.update(kv=0, file=0)

    assert [j["id"] for j in store._load_snapshot(db)["jobs"]] == ["a"]
    assert [j["id"] for j in store._load_snapshot(db)["jobs"]] == ["a"]
    assert reads == {"kv": 0, "file": 0}  # served from memory after the write

    store._persist_snapshot(db, {"jobs": [{"id": "a"}, {"id": "b"}]})
    assert len(store._load_snapshot(db)["jobs"]) == 2

    # A change on disk that did not go through _persist_snapshot is noticed.
    snap_file.write_text(json.dumps({"jobs": [{"id": "x"}, {"id": "y"}, {"id": "z"}]}), encoding="utf-8")
    os.utime(snap_file, ns=(1, 1))
    assert len(store._load_snapshot(db)["jobs"]) == 3
    assert reads["kv"] == 1  # one KV read, not two
