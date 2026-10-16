from fastapi.testclient import TestClient
import pytest
from app.main import app

client = TestClient(app)


def test_candidate_signup_and_login_flow():
    email = "new_candidate_123@example.com"
    password = "secret_password_123"

    # 1. Signup
    signup_res = client.post(
        "/auth/candidate/signup",
        json={"email": email, "password": password, "fullName": "Alex Rivera"},
    )
    assert signup_res.status_code == 200
    signup_data = signup_res.json()
    assert signup_data["success"] is True
    assert signup_data["email"] == email
    assert signup_data["needsOnboarding"] is True
    assert "token" in signup_data
    token = signup_data["token"]

    # 2. Duplicate signup should be rejected
    dup_res = client.post(
        "/auth/candidate/signup",
        json={"email": email, "password": password},
    )
    assert dup_res.status_code == 409
    assert "already exists" in dup_res.json()["detail"]

    # 3. Login with wrong password
    bad_login = client.post(
        "/auth/candidate/login",
        json={"email": email, "password": "wrong_password"},
    )
    assert bad_login.status_code == 401

    # 4. Login with correct password
    login_res = client.post(
        "/auth/candidate/login",
        json={"email": email, "password": password},
    )
    assert login_res.status_code == 200
    login_data = login_res.json()
    assert login_data["success"] is True
    assert login_data["email"] == email
    assert "token" in login_data

    # 5. Access /auth/me with Bearer token
    me_res = client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert me_res.status_code == 200
    me_data = me_res.json()
    assert me_data["email"] == email
    assert me_data["fullName"] == "Alex Rivera"
