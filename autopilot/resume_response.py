"""Validate resume bullet arrays from model responses without accepting objects as prose."""
import json


def parse_resume_bullets(value: object) -> list[str]:
    if isinstance(value, str):
        decoder = json.JSONDecoder()
        for index, char in enumerate(value):
            if char != "[":
                continue
            try:
                candidate, _ = decoder.raw_decode(value[index:])
            except ValueError:
                continue
            if isinstance(candidate, list) and candidate and all(isinstance(item, str) and item.strip() for item in candidate):
                return candidate
    elif isinstance(value, list) and value and all(isinstance(item, str) and item.strip() for item in value):
        return value
    raise ValueError("Resume response must contain a nonempty array of bullet strings")
