"""ATS Adapters package."""

from backend.autopilot.ats.adapters.ashby_adapter import AshbyAdapter
from backend.autopilot.ats.adapters.base_adapter import ApplicationAdapter
from backend.autopilot.ats.adapters.generic_adapter import GenericAdapter
from backend.autopilot.ats.adapters.greenhouse_adapter import GreenhouseAdapter
from backend.autopilot.ats.adapters.lever_adapter import LeverAdapter
from backend.autopilot.ats.adapters.workday_adapter import WorkdayAdapter


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
