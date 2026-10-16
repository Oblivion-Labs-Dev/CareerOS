import time
from unittest.mock import MagicMock
import pytest

from app.db.store import (
    EntityStore,
    KVStore,
    SessionLocal,
    _migrate_schema_if_needed,
    delete_entity,
    entity_count,
    get_entity,
    get_kv,
    list_entities,
    list_entities_by_json_equals,
    list_entities_where_json,
    set_kv,
    upsert_entity,
)
from app.services.auth import (
    extract_user_from_request,
    verify_jwt_token,
)


def test_schema_migration_is_idempotent():
    """Running migration repeatedly should never error or corrupt schema."""
    _migrate_schema_if_needed()
    _migrate_schema_if_needed()


def test_kv_store_multi_tenant_isolation():
    with SessionLocal() as db:
        # User A and User B set different values for the same key 'target_settings'
        set_kv(db, "target_settings", {"role": "Backend Lead"}, user_id="user_alice")
        set_kv(db, "target_settings", {"role": "Frontend Architect"}, user_id="user_bob")
        db.commit()

        val_alice = get_kv(db, "target_settings", user_id="user_alice")
        val_bob = get_kv(db, "target_settings", user_id="user_bob")
        val_default = get_kv(db, "target_settings", user_id="default")

        assert val_alice == {"role": "Backend Lead"}
        assert val_bob == {"role": "Frontend Architect"}
        assert val_default is None


def test_entity_store_multi_tenant_isolation():
    with SessionLocal() as db:
        uid_a = "user_alpha"
        uid_b = "user_beta"

        # Create job for Alpha
        job_a = upsert_entity(
            db,
            "aa_autopilot_job",
            {"company": "Stripe", "status": "QUEUED"},
            user_id=uid_a,
        )
        # Create job for Beta
        job_b = upsert_entity(
            db,
            "aa_autopilot_job",
            {"company": "OpenAI", "status": "QUEUED"},
            user_id=uid_b,
        )
        db.commit()

        # Query entities filtered by user_id
        jobs_a = list_entities(db, "aa_autopilot_job", user_id=uid_a)
        jobs_b = list_entities(db, "aa_autopilot_job", user_id=uid_b)

        assert any(j["id"] == job_a["id"] for j in jobs_a)
        assert not any(j["id"] == job_b["id"] for j in jobs_a)

        assert any(j["id"] == job_b["id"] for j in jobs_b)
        assert not any(j["id"] == job_a["id"] for j in jobs_b)

        # Entity count respects user_id
        count_a = entity_count(db, "aa_autopilot_job", user_id=uid_a)
        count_b = entity_count(db, "aa_autopilot_job", user_id=uid_b)
        assert count_a >= 1
        assert count_b >= 1

        # JSON queries respect user_id
        queued_a = list_entities_by_json_equals(
            db, "aa_autopilot_job", "$.status", "QUEUED", user_id=uid_a
        )
        assert all(j.get("userId") == uid_a for j in queued_a)

        # Delete entity with user_id scoping
        deleted = delete_entity(db, "aa_autopilot_job", job_a["id"], user_id=uid_a)
        assert deleted is True
        db.commit()

        assert get_entity(db, "aa_autopilot_job", job_a["id"], user_id=uid_a) is None


def test_jwt_verification_and_user_extraction():
    import jwt

    payload = {"sub": "usr_998877", "email": "candidate@example.com", "exp": int(time.time()) + 3600}
    token = jwt.encode(payload, "dummy_secret", algorithm="HS256")

    # In dev mode without configured secret, verify_jwt_token decodes unverified
    decoded = verify_jwt_token(token)
    assert decoded is not None
    assert decoded["sub"] == "usr_998877"

    # Test extract_user_from_request with Bearer header
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}"}
    req.cookies = {}

    user_id = extract_user_from_request(req)
    assert user_id == "usr_998877"

    # Fallback to default when no auth provided
    empty_req = MagicMock()
    empty_req.headers = {}
    empty_req.cookies = {}
    assert extract_user_from_request(empty_req) == "default"
