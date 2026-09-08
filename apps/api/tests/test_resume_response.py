import pytest

from app.services.application_assistant.resume_response import parse_resume_bullets


@pytest.mark.parametrize("value", ['["Built a service"]', 'Here are the bullets:\n```JSON\n["Built a service"]\n```', ["Built a service"]])
def test_bullet_array(value):
    assert parse_resume_bullets(value) == ["Built a service"]


@pytest.mark.parametrize("value", ['[{"invented": "object"}]', '[]', '[null]', '[""]', 'service unavailable'])
def test_invalid_bullets_rejected(value):
    with pytest.raises(ValueError):
        parse_resume_bullets(value)
