import pytest

from ledgerline_api.money import MoneyError, format_minor, to_minor


@pytest.mark.parametrize(
    ("amount", "currency", "minor"),
    [
        ("46.41", "EUR", 4641),
        ("1,234.50", "USD", 123450),
        ("1 234.5", "GBP", 123450),
        ("12000", "JPY", 12000),
        ("1.250", "KWD", 1250),
        ("-19.99", "EUR", -1999),  # credit notes carry negative amounts
    ],
)
def test_printed_amounts_become_minor_units(amount, currency, minor):
    assert to_minor(amount, currency) == minor


def test_trailing_zeros_beyond_the_currency_exponent_are_accepted():
    # Seen in real model output: a yen amount printed "125,000" came back as "125000.00".
    assert to_minor("125000.00", "JPY") == 125000
    assert to_minor("10.000", "EUR") == 1000


def test_extra_decimals_fail_instead_of_rounding():
    with pytest.raises(MoneyError, match="decimal places"):
        to_minor("10.005", "EUR")
    with pytest.raises(MoneyError, match="decimal places"):
        to_minor("1200.5", "JPY")


def test_european_decimal_comma_is_rejected_not_misread():
    # "1.234,56" must never silently become 1.23456 or 123456; the prompt asks for a dot decimal.
    with pytest.raises(MoneyError):
        to_minor("1.234,56", "EUR")


def test_unknown_currency_and_garbage_fail():
    with pytest.raises(MoneyError, match="unsupported currency"):
        to_minor("10.00", "XYZ")
    with pytest.raises(MoneyError, match="not an amount"):
        to_minor("ten", "EUR")
    with pytest.raises(MoneyError, match="not an amount"):
        to_minor("NaN", "EUR")


@pytest.mark.parametrize(("minor", "currency", "text"), [(4641, "EUR", "46.41"), (12000, "JPY", "12000"), (5, "USD", "0.05")])
def test_format_is_the_inverse_of_parse(minor, currency, text):
    assert format_minor(minor, currency) == text
    assert to_minor(text, currency) == minor


def test_format_minor_matches_the_fixtures_the_web_app_also_tests_against():
    import json
    from pathlib import Path

    fixtures = json.loads((Path(__file__).resolve().parents[3] / "packages/clients/fixtures/money.json").read_text())
    for case in fixtures["cases"]:
        assert format_minor(case["amount_minor"], case["currency"]) == case["formatted"], case
