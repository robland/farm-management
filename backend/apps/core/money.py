"""Monetary helpers: Decimal only, rounding to the ISO 4217 minor unit (CLAUDE.md §11)."""

from decimal import ROUND_HALF_UP, Decimal

from apps.core.exceptions import BusinessRuleError

# ISO 4217 minor unit exponents for currencies expected in the target context.
# Unlisted currencies must be added explicitly (no silent default).
CURRENCY_EXPONENTS: dict[str, int] = {
    "XAF": 0,
    "XOF": 0,
    "CDF": 2,
    "EUR": 2,
    "USD": 2,
    "GBP": 2,
    "NGN": 2,
    "GHS": 2,
    "KES": 2,
    "MAD": 2,
    "ZAR": 2,
}


def currency_exponent(currency: str) -> int:
    try:
        return CURRENCY_EXPONENTS[currency]
    except KeyError as exc:
        raise BusinessRuleError(
            f"Devise non prise en charge : {currency}.", field_errors={"currency": ["Inconnue."]}
        ) from exc


def round_amount(amount: Decimal, currency: str) -> Decimal:
    return amount.quantize(Decimal(1).scaleb(-currency_exponent(currency)), rounding=ROUND_HALF_UP)


def check_amount_precision(amount: Decimal, currency: str, field: str = "amount") -> None:
    """Reject amounts with more decimals than the currency allows (e.g. 10.5 XAF)."""
    if amount != round_amount(amount, currency):
        raise BusinessRuleError(
            f"Montant trop précis pour la devise {currency}.",
            field_errors={field: [f"Au plus {currency_exponent(currency)} décimale(s)."]},
        )
