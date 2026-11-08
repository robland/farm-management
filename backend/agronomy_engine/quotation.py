"""Quotation totals (AGRONOMY_ENGINE.md §8, FR-043).

Line totals are rounded to the currency minor unit (ROUND_HALF_UP) line by
line; unpriced lines are excluded from totals and reported.
"""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from agronomy_engine.errors import InvalidInputError, require_non_negative
from agronomy_engine.result import CalculationResult, Quantity


@dataclass(frozen=True)
class QuoteLineInput:
    ref: str
    description: str
    quantity: Decimal
    unit_price: Decimal | None


@dataclass(frozen=True)
class QuoteInput:
    currency: str
    currency_exponent: int
    lines: list[QuoteLineInput]
    discount_amount: Decimal | None = None
    tax_rate: Decimal | None = None


def round_money(amount: Decimal, exponent: int) -> Decimal:
    return amount.quantize(Decimal(1).scaleb(-exponent), rounding=ROUND_HALF_UP)


def compute_quote(data: QuoteInput) -> tuple[CalculationResult, dict[str, Decimal | None]]:
    if data.currency_exponent < 0:
        raise InvalidInputError("currency_exponent", "doit être positif")
    totals: dict[str, Decimal | None] = {}
    subtotal = Decimal(0)
    unpriced = []
    for line in data.lines:
        require_non_negative(f"lines.{line.ref}.quantity", line.quantity)
        if line.unit_price is None:
            totals[line.ref] = None
            unpriced.append(line.description)
            continue
        require_non_negative(f"lines.{line.ref}.unit_price", line.unit_price)
        amount = round_money(line.quantity * line.unit_price, data.currency_exponent)
        totals[line.ref] = amount
        subtotal += amount
    discount = data.discount_amount or Decimal(0)
    require_non_negative("discount_amount", discount)
    if discount > subtotal:
        raise InvalidInputError("discount_amount", "supérieure au sous-total")
    taxable = subtotal - discount
    tax = Decimal(0)
    if data.tax_rate is not None:
        require_non_negative("tax_rate", data.tax_rate)
        tax = round_money(taxable * data.tax_rate, data.currency_exponent)
    total = taxable + tax
    warnings = (
        [f"{len(unpriced)} ligne(s) sans prix exclue(s) du total : " + ", ".join(unpriced)]
        if unpriced
        else []
    )
    result = CalculationResult(
        calc_type="quotation.totals",
        inputs={
            "currency": Quantity(data.currency),
            "line_count": Quantity(len(data.lines), "lignes"),
            "discount_amount": Quantity(discount, data.currency),
            "tax_rate": Quantity(data.tax_rate, "ratio"),
        },
        outputs={
            "subtotal": Quantity(subtotal, data.currency),
            "tax_amount": Quantity(tax, data.currency),
            "total": Quantity(total, data.currency),
            "unpriced_line_count": Quantity(len(unpriced), "lignes"),
        },
        formula="total_ligne = arrondi(quantité × prix unitaire) ; sous-total = Σ ; "
        "total = (sous-total − remise) × (1 + taxe)",
        assumptions=[
            f"Arrondi au demi supérieur à {data.currency_exponent} décimale(s) par ligne."
        ],
        warnings=warnings,
    )
    return result, totals
