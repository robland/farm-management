"""Versioned JSON schemas of the AI outputs (CLAUDE.md §10: validated structured outputs).

Numbers are exchanged as decimal STRINGS to avoid binary floating point.
Any response that does not match its schema is rejected, never repaired.
"""

from typing import Any

from apps.production_plans.services import PLANTING_FIELDS

EXTRACTION_SCHEMA_VERSION = "extraction.v1"
PLAN_DRAFT_SCHEMA_VERSION = "plan_draft.v1"

_NULLABLE_STRING = {"type": ["string", "null"]}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


EXTRACTION_SCHEMA: dict[str, Any] = _object(
    {
        "items": {
            "type": "array",
            "items": _object(
                {
                    "key": {"type": "string"},
                    "value": _NULLABLE_STRING,
                    "value_min": _NULLABLE_STRING,
                    "value_max": _NULLABLE_STRING,
                    "value_text": _NULLABLE_STRING,
                    "unit": {"type": "string"},
                    "page": {"type": ["integer", "null"]},
                    "quote": {"type": "string"},
                    "confidence": _NULLABLE_STRING,
                }
            ),
        },
        "missing": {"type": "array", "items": {"type": "string"}},
        "notes": {"type": "string"},
    }
)

_SOURCE = {"type": "string", "enum": ["document", "ai_suggestion"]}

PLAN_DRAFT_SCHEMA: dict[str, Any] = _object(
    {
        "planting": {
            "type": "array",
            "items": _object(
                {
                    "field": {"type": "string", "enum": PLANTING_FIELDS},
                    "value": _NULLABLE_STRING,
                    "source": _SOURCE,
                    "technical_key": _NULLABLE_STRING,
                    "rationale": {"type": "string"},
                }
            ),
        },
        "phases": {
            "type": "array",
            "items": _object(
                {
                    "phase_code": {"type": "string"},
                    "duration_days": {"type": ["integer", "null"]},
                    "source": _SOURCE,
                    "technical_key": _NULLABLE_STRING,
                    "rationale": {"type": "string"},
                }
            ),
        },
        "missing_info": {
            "type": "array",
            "items": _object(
                {
                    "field": {"type": "string"},
                    "question": {"type": "string"},
                }
            ),
        },
        "remarks": {"type": "string"},
    }
)
