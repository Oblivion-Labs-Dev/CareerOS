"""ATS Adapters package."""

from autopilot.adapters.ashby_adapter import AshbyAdapter
from autopilot.adapters.base_adapter import ApplicationAdapter
from autopilot.adapters.generic_adapter import GenericAdapter
from autopilot.adapters.greenhouse_adapter import GreenhouseAdapter
from autopilot.adapters.lever_adapter import LeverAdapter
from autopilot.adapters.workday_adapter import WorkdayAdapter


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
