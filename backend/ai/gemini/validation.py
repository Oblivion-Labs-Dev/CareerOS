"""A small JSON Schema check for machine-consumed Gemini replies.

Gemini is asked for `response_format: json_schema` with `strict: true`, and it
honours that nearly always. Nearly is the problem: a reply that omits a required
field, or returns `"confidence": "high"` where a number was specified, parses
perfectly well as JSON and then poisons whatever consumes it. So every reply is
re-checked here against the same schema that was sent.

This validates the subset of JSON Schema the task schemas in `schemas.py`
actually use - object/array/string/number/integer/boolean, `properties`,
`required`, `enum`, `items`, `minimum`/`maximum` - rather than pulling in
`jsonschema`, which is not currently a dependency and would be one more thing
to install on a machine where the whole point is keeping the footprint small.

Anything the subset does not cover is treated as valid rather than invalid: an
unrecognised keyword must not reject a reply that is genuinely correct.
"""

from __future__ import annotations

from typing import Any

_TYPES: dict[str, tuple[type, ...] | type] = {
    "object": dict,
    "array": list,
    "string": str,
    "boolean": bool,
    "null": type(None),
}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "number":
        # bool is a subclass of int in Python; a boolean is not a number here.
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "boolean":
        return isinstance(value, bool)
    checker = _TYPES.get(expected)
    if checker is None:
        return True
    return isinstance(value, checker)


def validate(value: Any, schema: dict[str, Any], path: str = "$") -> list[str]:
    """Return a list of human-readable problems. Empty means the value is fine."""
    errors: list[str] = []
    if not isinstance(schema, dict):
        return errors

    expected = schema.get("type")
    if isinstance(expected, str) and not _type_ok(value, expected):
        errors.append(f"{path}: expected {expected}, got {type(value).__name__}")
        # Nothing below can be meaningful once the type is wrong.
        return errors
    if isinstance(expected, list) and not any(_type_ok(value, t) for t in expected):
        errors.append(f"{path}: expected one of {expected}, got {type(value).__name__}")
        return errors

    choices = schema.get("enum")
    if isinstance(choices, list) and value not in choices:
        errors.append(f"{path}: {value!r} is not one of {choices}")

    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        for name in schema.get("required") or []:
            if name not in value:
                errors.append(f"{path}: missing required field {name!r}")
        for name, sub_schema in properties.items():
            if name in value:
                errors.extend(validate(value[name], sub_schema, f"{path}.{name}"))

    if isinstance(value, list):
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                errors.extend(validate(item, item_schema, f"{path}[{index}]"))
        minimum_items = schema.get("minItems")
        if isinstance(minimum_items, int) and len(value) < minimum_items:
            errors.append(f"{path}: expected at least {minimum_items} items, got {len(value)}")

    if isinstance(value, (int, float)) and not isinstance(value, bool):
        low = schema.get("minimum")
        high = schema.get("maximum")
        if isinstance(low, (int, float)) and value < low:
            errors.append(f"{path}: {value} is below the minimum {low}")
        if isinstance(high, (int, float)) and value > high:
            errors.append(f"{path}: {value} is above the maximum {high}")

    return errors
