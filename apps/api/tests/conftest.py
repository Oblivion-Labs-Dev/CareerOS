"""Shared pytest configuration."""

from __future__ import annotations

import os

import pytest


@pytest.fixture(scope="session", autouse=True)
def isolated_browser_profile(tmp_path_factory: pytest.TempPathFactory) -> None:
    """Keep Playwright integration tests from hijacking the dev browser profile."""
    profile = tmp_path_factory.mktemp("aa_browser_profile")
    os.environ["AA_BROWSER_PROFILE_DIR"] = str(profile)
    yield
    os.environ.pop("AA_BROWSER_PROFILE_DIR", None)
