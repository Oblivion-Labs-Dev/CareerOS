"""Routes that should not be tracked as actionable API errors."""

IGNORE_ERROR_PATHS: frozenset[str] = frozenset(
    {
        "/favicon.ico",
        "/robots.txt",
    }
)

IGNORE_ERROR_PATH_PREFIXES: tuple[str, ...] = (
    "/dev/repair/",
    "/dev/demo/",
)


def should_track_api_error(method: str, path: str) -> bool:
    if path in IGNORE_ERROR_PATHS:
        return False
    return not any(path.startswith(prefix) for prefix in IGNORE_ERROR_PATH_PREFIXES)
