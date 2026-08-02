"""Provider detection and registry."""

from __future__ import annotations

from app.services.application_assistant.providers.base import ProviderAdapter
from app.services.application_assistant.providers.greenhouse import GreenhouseAdapter
from app.services.application_assistant.providers.lever import LeverAdapter
from app.services.application_assistant.providers.workday import WorkdayAdapter
from app.services.application_assistant.url_validation import detect_provider_from_url

_ADAPTERS: dict[str, ProviderAdapter] = {
    "greenhouse": GreenhouseAdapter(),
    "workday": WorkdayAdapter(),
    "lever": LeverAdapter(),
}


def get_adapter(provider: str) -> ProviderAdapter | None:
    return _ADAPTERS.get(provider)


def detect_provider(url: str, page_content: str = "") -> tuple[str, ProviderAdapter | None, bool]:
    """Detect provider from URL and page content. Returns (name, adapter, supported)."""
    url_provider = detect_provider_from_url(url)
    adapter = get_adapter(url_provider)
    if adapter:
        detection = adapter.detect(url, page_content)
        return detection.provider, adapter, detection.supported

    # Try all adapters
    for _name, adp in _ADAPTERS.items():
        detection = adp.detect(url, page_content)
        if detection.confidence > 0.5:
            return detection.provider, adp, detection.supported

    return "unknown", None, False


def list_providers() -> list[dict[str, str | bool]]:
    return [
        {"name": adp.name, "supported": adp.supported}
        for adp in _ADAPTERS.values()
    ]
