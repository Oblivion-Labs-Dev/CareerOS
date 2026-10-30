"""CAREEROS_ENV=production must refuse to start with the login gate off.

The gate is a no-op until an admin password is set (so a local checkout is not
locked out); deployed, that default left every endpoint open.
"""

import pytest

from app import main


def test_production_without_a_password_refuses_to_start(monkeypatch):
    monkeypatch.setenv("CAREEROS_ENV", "production")
    monkeypatch.setattr(main.settings, "career_os_admin_password", "")
    monkeypatch.setattr(main.settings, "career_os_session_secret", "s" * 32)
    with pytest.raises(RuntimeError, match="CAREER_OS_ADMIN_PASSWORD"):
        main._refuse_unauthenticated_production()


def test_production_without_a_session_secret_refuses_to_start(monkeypatch):
    monkeypatch.setenv("CAREEROS_ENV", "production")
    monkeypatch.setattr(main.settings, "career_os_admin_password", "pw")
    monkeypatch.setattr(main.settings, "career_os_session_secret", "")
    with pytest.raises(RuntimeError, match="CAREER_OS_SESSION_SECRET"):
        main._refuse_unauthenticated_production()


def test_production_with_credentials_starts(monkeypatch):
    monkeypatch.setenv("CAREEROS_ENV", "production")
    monkeypatch.setattr(main.settings, "career_os_admin_password", "pw")
    monkeypatch.setattr(main.settings, "career_os_session_secret", "s" * 32)
    main._refuse_unauthenticated_production()


def test_local_runs_are_unchanged(monkeypatch):
    monkeypatch.delenv("CAREEROS_ENV", raising=False)
    monkeypatch.setattr(main.settings, "career_os_admin_password", "")
    main._refuse_unauthenticated_production()
