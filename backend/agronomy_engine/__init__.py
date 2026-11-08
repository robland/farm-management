"""Deterministic agronomic calculation engine (docs/architecture/AGRONOMY_ENGINE.md).

Pure Python: no Django, no database, no network, no randomness. Every public
function returns a `CalculationResult` documenting inputs, units, formula,
assumptions and warnings. No agronomic default value is ever applied: a
missing input raises `MissingInputError`.
"""

ENGINE_VERSION = "1.0.0"
