"""ATS Adapters package."""

from app.services.application_assistant.adapters.ashby_adapter import AshbyAdapter
from app.services.application_assistant.adapters.base_adapter import ApplicationAdapter
from app.services.application_assistant.adapters.generic_adapter import GenericAdapter
from app.services.application_assistant.adapters.greenhouse_adapter import GreenhouseAdapter
from app.services.application_assistant.adapters.lever_adapter import LeverAdapter
from app.services.application_assistant.adapters.workday_adapter import WorkdayAdapter


ADAPTERS: list[ApplicationAdapter] = [
    GreenhouseAdapter(),
    LeverAdapter(),
    AshbyAdapter(),
    WorkdayAdapter(),
    GenericAdapter(),
]


async def resolve_adapter(url: str, html_content: str = "") -> ApplicationAdapter:
    for adapter in ADAPTERS:
        if await adapter.can_handle(url, html_content):
            return adapter
    return GenericAdapter()
