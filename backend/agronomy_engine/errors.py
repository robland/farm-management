from collections.abc import Iterable, Mapping
from decimal import Decimal
from typing import Any


class EngineError(Exception):
    pass


class MissingInputError(EngineError):
    """One or more required inputs are absent. No default value is ever assumed."""

    def __init__(self, fields: Iterable[str], reason: str = "") -> None:
        self.fields = sorted(set(fields))
        self.reason = reason
        super().__init__(f"Missing inputs: {', '.join(self.fields)} {reason}".strip())


class InvalidInputError(EngineError):
    def __init__(self, field: str, reason: str) -> None:
        self.field = field
        self.reason = reason
        super().__init__(f"{field}: {reason}")


def require(values: Mapping[str, Any], names: Iterable[str], reason: str = "") -> None:
    missing = [name for name in names if values.get(name) is None]
    if missing:
        raise MissingInputError(missing, reason)


def present[T](value: T | None, name: str) -> T:
    """Return a value already checked by `require()` (narrows the Optional type)."""
    if value is None:
        raise MissingInputError([name])
    return value


def require_positive(name: str, value: Decimal | int) -> None:
    if value <= 0:
        raise InvalidInputError(name, "doit être strictement positif")


def require_non_negative(name: str, value: Decimal | int) -> None:
    if value < 0:
        raise InvalidInputError(name, "doit être positif ou nul")


def require_rate(name: str, value: Decimal, *, allow_zero: bool = False) -> None:
    low_ok = value >= 0 if allow_zero else value > 0
    if not low_ok or value > 1:
        raise InvalidInputError(name, "doit être compris entre 0 et 1")
