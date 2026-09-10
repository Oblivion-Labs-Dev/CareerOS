"""An adapter must never report a submission it did not perform.

The Workday and Generic adapters were stubs that returned
`{"submitted": True, "evidence": {"confirmationText": "..."}}` without touching
the page at all — and Generic is the fallback for *every* unrecognised careers
site. Wired into the runner, that would have recorded jobs as SUBMITTED with
invented confirmation evidence for applications that were never sent.
"""

import pytest

from app.services.application_assistant.adapters import ADAPTERS, resolve_adapter
from app.services.application_assistant.adapters.base_adapter import (
    AdapterNotImplementedError,
)
from app.services.application_assistant.adapters.generic_adapter import GenericAdapter
from app.services.application_assistant.adapters.workday_adapter import WorkdayAdapter

UNIMPLEMENTED = [WorkdayAdapter(), GenericAdapter()]


@pytest.mark.parametrize("adapter", UNIMPLEMENTED, ids=lambda a: a.name)
@pytest.mark.anyio
async def test_unimplemented_adapters_refuse_to_claim_a_submission(adapter):
    with pytest.raises(AdapterNotImplementedError):
        await adapter.submit_application(object())


@pytest.mark.parametrize("adapter", UNIMPLEMENTED, ids=lambda a: a.name)
@pytest.mark.anyio
async def test_unimplemented_adapters_fail_pre_submit(adapter):
    ok, why = await adapter.verify_pre_submit(object(), [])
    assert ok is False
    assert why


@pytest.mark.parametrize("adapter", UNIMPLEMENTED, ids=lambda a: a.name)
@pytest.mark.anyio
async def test_unimplemented_adapters_do_not_invent_a_field_list(adapter):
    with pytest.raises(AdapterNotImplementedError):
        await adapter.inspect_fields("https://example.com/job/1")


@pytest.mark.anyio
async def test_generic_is_still_the_fallback():
    adapter = await resolve_adapter("https://careers.example.com/apply/123")
    assert adapter.name == "generic"


def test_no_adapter_hardcodes_candidate_identity():
    # A missing resolved answer must leave the field empty so the pre-submit
    # check catches it — never fall back to a real person's contact details
    # baked into the source.
    import inspect

    for adapter in ADAPTERS:
        source = inspect.getsource(type(adapter))
        lowered = source.lower()
        assert "amsborse" not in lowered, f"{adapter.name} hardcodes an email address"
        assert "akshay" not in lowered, f"{adapter.name} hardcodes a candidate name"
        assert "425-336" not in lowered, f"{adapter.name} hardcodes a phone number"
