---
status: accepted
date: 2026-10-30
---

# Money is integer minor units plus an ISO currency; the model returns printed strings and code converts

Every amount is stored and passed around as `BIGINT` minor units (cents, pence, yen) with a 3-letter
currency. The model is asked to copy amounts as plain decimal strings ("1933.94"); `money.to_minor` converts
them using the currency's exponent and **rejects** any amount that would need rounding ("10.005" EUR) instead
of rounding it. Trailing zeros are accepted: "125000.00" JPY is exactly 125000. Floats never touch an amount.

## Considered options

- **NUMERIC(18,2) columns with Decimal in Python**: exact, but bakes in two decimals, which is wrong for JPY
  (0) and KWD (3), and invites a later migration.
- **Ask the model for minor units directly**: one fewer step, but it makes the model do arithmetic, and a
  JPY/EUR exponent mistake would be silent.
- **Floats**: rejected outright; rounding errors on payment amounts.

## Assumptions

- The model can reliably copy amounts as dot-decimal strings without thousands separators. European
  "1.234,56" input is rejected rather than guessed; the eval will show whether that happens in practice.
- The model doesn't always respect the currency's decimals: on 2026-10-30 gemma4:12b returned "125000.00" for
  a yen amount printed "125,000". That's why only value-changing extra digits are rejected.
- The currency table in `money.py` holds only currencies seen so far (EUR, USD, GBP, CHF, JPY, KWD) and grows
  when real input needs it; the stdlib has no ISO-4217 table.
