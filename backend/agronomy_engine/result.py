from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from agronomy_engine import ENGINE_VERSION

Value = Decimal | int | str | bool | None


@dataclass(frozen=True)
class Quantity:
    value: Value
    unit: str = ""

    def to_dict(self) -> dict[str, Any]:
        value = str(self.value) if isinstance(self.value, Decimal) else self.value
        return {"value": value, "unit": self.unit}


@dataclass(frozen=True)
class CalculationResult:
    calc_type: str
    inputs: dict[str, Quantity]
    outputs: dict[str, Quantity]
    formula: str
    assumptions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    engine_version: str = ENGINE_VERSION
    details: dict[str, Any] = field(default_factory=dict)

    def output(self, name: str) -> Any:
        return self.outputs[name].value

    def to_dict(self) -> dict[str, Any]:
        return {
            "calc_type": self.calc_type,
            "engine_version": self.engine_version,
            "inputs": {k: v.to_dict() for k, v in self.inputs.items()},
            "outputs": {k: v.to_dict() for k, v in self.outputs.items()},
            "formula": self.formula,
            "assumptions": list(self.assumptions),
            "warnings": list(self.warnings),
            "details": self.details,
        }
