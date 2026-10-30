"""Money is always an integer count of the currency's minor unit (cents, pence, yen) plus an ISO-4217 code.

Floats never touch an amount. See docs/adr/0003-money-as-integer-minor-units.md.
"""

from decimal import Decimal, InvalidOperation

# Minor-unit exponents for the currencies Ledgerline accepts today. The stdlib has no ISO-4217 table;
# extend this when a new currency shows up in real input rather than guessing the whole list.
CURRENCY_EXPONENTS: dict[str, int] = {
    "EUR": 2,
    "USD": 2,
    "GBP": 2,
    "CHF": 2,
    "JPY": 0,
    "KWD": 3,
}


class MoneyError(ValueError):
    pass


def to_minor(amount: str, currency: str) -> int:
    """Turn a printed amount like "1,234.50" into minor units for `currency`.

    Thousands separators (comma, space, apostrophe) are dropped; the dot is the decimal point. More decimal
    places than the currency allows is an error, never rounded: a wrong invoice total must fail loudly.
    """
    exponent = CURRENCY_EXPONENTS.get(currency)
    if exponent is None:
        raise MoneyError(f"unsupported currency {currency!r}")

    cleaned = amount.strip().replace(",", "").replace(" ", "").replace("'", "")
    try:
        value = Decimal(cleaned)
    except InvalidOperation:
        raise MoneyError(f"not an amount: {amount!r}") from None
    if not value.is_finite():
        raise MoneyError(f"not an amount: {amount!r}")

    scaled = value.scaleb(exponent)
    # Trailing zeros are harmless ("125000.00" JPY is exactly 125000); only digits that would need
    # rounding are rejected, e.g. "10.005" EUR.
    if scaled != scaled.to_integral_value():
        raise MoneyError(f"{amount!r} has more than {exponent} decimal places for {currency}")

    return int(scaled)


def format_minor(minor: int, currency: str) -> str:
    """Inverse of to_minor, without thousands separators: 4641 EUR -> "46.41"."""
    exponent = CURRENCY_EXPONENTS.get(currency)
    if exponent is None:
        raise MoneyError(f"unsupported currency {currency!r}")
    return f"{Decimal(minor).scaleb(-exponent):.{exponent}f}"
