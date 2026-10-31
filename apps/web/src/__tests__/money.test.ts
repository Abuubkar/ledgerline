import { readFileSync } from "node:fs";
import { join } from "node:path";
import { formatMinor, formatMoney } from "@/lib/money";

// The same fixtures Python's format_minor is tested against (apps/api/tests/test_money.py).
const fixtures: { cases: { amount_minor: number; currency: string; formatted: string }[] } =
  JSON.parse(readFileSync(join(__dirname, "../../../../packages/clients/fixtures/money.json"), "utf8"));

test.each(fixtures.cases)("formatMinor($amount_minor, $currency) is $formatted, as in Python", ({ amount_minor, currency, formatted }) => {
  expect(formatMinor(amount_minor, currency)).toBe(formatted);
});

test("display adds the symbol and thousands separators to the same digits", () => {
  expect(formatMoney(3618543, "EUR")).toBe("€36,185.43");
  expect(formatMoney(376, "JPY")).toBe("¥376");
  expect(formatMoney(-100, "GBP")).toBe("−£1.00");
  expect(formatMoney(null, "EUR")).toBe("—");
});

test("an amount JavaScript can't hold exactly is refused rather than rounded", () => {
  expect(() => formatMinor(2 ** 53 + 2, "EUR")).toThrow("not an exact integer");
});
