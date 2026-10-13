"""A required custom dropdown left empty reaches review with its real choices.

The verification scan reads a closed react-select, which lists no options in
the DOM. The options read when the form was discovered have to travel with the
issue, or the review asks a free-text question whose answer matches no option.
"""

import asyncio

from app.services.application_assistant.browser_verifier import verify_browser_dom_state
from app.services.application_assistant.playwright_autopilot_executor import (
    _known_field_options,
    _options_by_field,
)

AI_SCALE = [
    "1 - Not familiar at all",
    "2 - Slightly familiar",
    "3 - Moderately familiar",
    "4 - Very familiar",
    "5 - Expert level",
]


class _Frame:
    def __init__(self, fields):
        self.fields = fields
        self.calls = 0

    async def evaluate(self, *_args, **_kwargs):
        self.calls += 1
        return self.fields if self.calls == 1 else None


def _empty_dropdown(label="How familiar are you with AI tools?*"):
    return {
        "id": "question_68341596", "name": "", "label": label, "group": "",
        "type": "div", "isCombobox": True, "value": "", "required": True, "options": [],
    }


def _missing(result):
    return [i for i in result.issues if i.issue_type == "MISSING_REQUIRED"]


def test_discovered_options_are_keyed_by_id_and_label():
    known = _options_by_field([
        {"id": "question_68341596", "label": "How familiar  are you\nwith AI tools?*", "options": AI_SCALE},
        {"id": "first_name", "label": "First Name", "options": []},
    ])

    assert _known_field_options(known, "question_68341596", "") == AI_SCALE
    assert _known_field_options(known, "", "how familiar are you with ai tools?*") == AI_SCALE
    assert _known_field_options(known, "first_name", "First Name") == []


def test_empty_required_dropdown_carries_discovered_options():
    known = _options_by_field([{"id": "question_68341596", "label": "x", "options": AI_SCALE}])

    result = asyncio.run(verify_browser_dom_state(_Frame([_empty_dropdown()]), [], {}, known_options=known))

    [issue] = _missing(result)
    assert issue.options == AI_SCALE


def test_dropdown_matched_by_label_when_ids_differ():
    known = _options_by_field([
        {"id": "other-id", "label": "How familiar are you with AI tools?*", "options": AI_SCALE},
    ])

    result = asyncio.run(verify_browser_dom_state(_Frame([_empty_dropdown()]), [], {}, known_options=known))

    [issue] = _missing(result)
    assert issue.options == AI_SCALE


def test_without_known_options_the_issue_has_none():
    result = asyncio.run(verify_browser_dom_state(_Frame([_empty_dropdown()]), [], {}))

    [issue] = _missing(result)
    assert issue.options == []
