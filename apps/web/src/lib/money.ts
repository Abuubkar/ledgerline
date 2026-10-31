// Money is integer minor units plus an ISO currency, as in the API (ADR 0003). formatMinor must give exactly what
// Python's ledgerline_api.money.format_minor gives; both are tested against packages/clients/fixtures/money.json.
const EXPONENTS: Record<string, number> = { EUR: 2, USD: 2, GBP: 2, CHF: 2, JPY: 0, KWD: 3 };

export function exponentOf(currency: string): number {
  const exponent = EXPONENTS[currency];
  if (exponent === undefined) throw new Error(`unsupported currency ${currency}`);
  return exponent;
}

/** 4641 EUR → "46.41". Integer arithmetic on the digits: never divides, so no float can round an amount. */
export function formatMinor(minor: number, currency: string): string {
  if (!Number.isSafeInteger(minor)) throw new Error(`${minor} is not an exact integer amount`);
  const exponent = exponentOf(currency);
  const digits = String(Math.abs(minor)).padStart(exponent + 1, "0");
  const units = digits.slice(0, digits.length - exponent);
  const sign = minor < 0 ? "-" : "";
  return exponent ? `${sign}${units}.${digits.slice(-exponent)}` : `${sign}${units}`;
}

/** For display: the currency's symbol and thousands separators, from the same exact digits. */
export function formatMoney(minor: number | null | undefined, currency: string | null | undefined): string {
  if (minor == null || !currency) return "—";
  const [units, fraction] = formatMinor(minor, currency).replace("-", "").split(".");
  const symbol = new Intl.NumberFormat("en-US", { style: "currency", currency }).formatToParts(0).find(p => p.type === "currency")?.value ?? `${currency} `;
  const grouped = units.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return `${minor < 0 ? "−" : ""}${symbol}${grouped}${fraction ? "." + fraction : ""}`;
}
