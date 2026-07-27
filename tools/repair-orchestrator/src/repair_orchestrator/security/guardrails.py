from __future__ import annotations

import fnmatch
from pathlib import Path

from repair_orchestrator.config import settings


def protected_directories() -> list[str]:
    return [item.strip() for item in settings.protected_directories.split(",") if item.strip()]


def protected_patterns() -> list[str]:
    return [item.strip() for item in settings.protected_file_patterns.split(",") if item.strip()]


def _normalize_path(relative_path: str) -> str:
    return relative_path.replace("\\", "/").removeprefix("./")


def is_protected_path(relative_path: str) -> bool:
    normalized = _normalize_path(relative_path)
    for directory in protected_directories():
        dir_norm = directory.replace("\\", "/").rstrip("/")
        if normalized == dir_norm or normalized.startswith(dir_norm + "/"):
            return True
    for pattern in protected_patterns():
        if fnmatch.fnmatch(normalized, pattern):
            return True
    return False


def validate_patch_files(changed_files: list[str], diff_bytes: int) -> tuple[bool, list[str]]:
    violations: list[str] = []
    if len(changed_files) > settings.max_changed_files:
        violations.append(f"Changed file count {len(changed_files)} exceeds max {settings.max_changed_files}")
    if diff_bytes > settings.max_diff_bytes:
        violations.append(f"Diff size {diff_bytes} exceeds max {settings.max_diff_bytes}")
    for file_path in changed_files:
        if is_protected_path(file_path):
            violations.append(f"Protected file modified: {file_path}")
    return len(violations) == 0, violations


def requires_human_review(
    component: str,
    changed_files: list[str],
    categories: list[str] | None = None,
    extra_context: str = "",
) -> bool:
    required = categories or [
        item.strip()
        for item in settings.required_human_review_categories.split(",")
        if item.strip()
    ]
    haystack = " ".join([component, extra_context, *changed_files]).lower()
    triggers = {
        "database": ("migration", "sqlalchemy", "db/", "database"),
        "authentication": ("auth", "login", "session", "api_key"),
        "authorization": ("permission", "rbac", "authorize"),
        "billing": ("billing", "stripe", "payment"),
        "privacy": ("privacy", "pii", "gdpr"),
        "infrastructure": (".github", "docker", "deploy", "ci.yml"),
        "extension-permissions": ("manifest.json", "permissions"),
        "resume-processing": ("resume", "corpus", "pypdf"),
        "job-application": ("application", "autofill", "apply"),
    }
    for category in required:
        keywords = triggers.get(category, (category.replace("-", "_"), category.replace("-", " ")))
        if any(keyword in haystack for keyword in keywords):
            return True
    return False
