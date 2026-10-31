// How invoices, problems and proposals are put into words for a reviewer. Plain language, no internal codes:
// the API stores terse reasons ("billed 46, received 45"); a person reads sentences.

export type Reason = { code: string; detail: string; line?: string | null };
type Money = { amountMinor: number; currency: string } | null | undefined;
type ListLike = { status: string; invalidFields?: unknown; match?: { reasons: Reason[] } | null };

export const STATUS: Record<string, { label: string; tone: string; icon: string }> = {
  received: { label: "Received", tone: "", icon: "inbox" },
  extracting: { label: "Reading", tone: "info", icon: "loader" },
  extracted: { label: "Read", tone: "", icon: "file-check" },
  partially_extracted: { label: "Partly read", tone: "warn", icon: "file-warning" },
  exception: { label: "Exception", tone: "bad", icon: "circle-alert" },
  failed: { label: "Failed", tone: "bad", icon: "circle-x" },
  matched: { label: "Matched", tone: "ok", icon: "circle-check" },
};

export const PROBLEM: Record<string, { label: string; tone: string; icon: string }> = {
  price_variance: { label: "Price above PO", tone: "bad", icon: "tag" },
  short_shipment: { label: "Short shipment", tone: "bad", icon: "package-minus" },
  not_received: { label: "Nothing received", tone: "warn", icon: "package-x" },
  quantity_mismatch: { label: "Quantity ≠ received", tone: "bad", icon: "scale" },
  quantity_over_po: { label: "More than ordered", tone: "bad", icon: "scale" },
  line_not_on_po: { label: "Line not on PO", tone: "bad", icon: "list-x" },
  line_unreadable: { label: "Unreadable line", tone: "warn", icon: "scan-text" },
  no_lines: { label: "No lines", tone: "warn", icon: "list-x" },
  po_not_found: { label: "PO not found", tone: "warn", icon: "file-question" },
  po_missing: { label: "No PO number", tone: "warn", icon: "file-question" },
  vendor_mismatch: { label: "Other vendor", tone: "bad", icon: "building-2" },
  currency_mismatch: { label: "Other currency", tone: "bad", icon: "coins" },
  duplicate: { label: "Possible duplicate", tone: "bad", icon: "copy" },
  totals: { label: "Totals don't add up", tone: "warn", icon: "calculator" },
  field: { label: "Unusable field", tone: "warn", icon: "circle-alert" },
};

export type Problem = Reason & { ref?: string };

/** Why an invoice was stopped: its match reasons plus fields extraction couldn't use (duplicates, totals). */
export function problems(inv: ListLike): Problem[] {
  const out: Problem[] = (inv.match?.reasons ?? []).map(r => ({ code: r.code, detail: r.detail, line: r.line }));
  for (const [field, why] of Object.entries((inv.invalidFields ?? {}) as Record<string, string>)) {
    if (field === "invoice_number" && why.startsWith("duplicate")) {
      out.push({ code: "duplicate", detail: why, ref: why.match(/[0-9a-f-]{36}/)?.[0] });
    } else if (field === "total") out.push({ code: "totals", detail: why });
    else out.push({ code: "field", detail: `${field.replaceAll("_", " ")}: ${why}` });
  }
  return out;
}

export function sentence(code: string, detail: string): string {
  let m: RegExpExecArray | null;
  if ((code === "short_shipment" || code === "quantity_mismatch") && (m = /billed ([\d.]+), received ([\d.]+)/.exec(detail)))
    return code === "short_shipment" ? `Billed for ${m[1]}, but only ${m[2]} were received.` : `Billed for ${m[1]}, but ${m[2]} were received.`;
  if (code === "quantity_over_po" && (m = /billed ([\d.]+), ordered ([\d.]+)/.exec(detail))) return `Billed for ${m[1]}, but only ${m[2]} were ordered.`;
  if (code === "price_variance" && (m = /unit price ([\d.]+) vs PO ([\d.]+) \(([+-][\d.]+)%, tolerance ([\d.]+)%\)/.exec(detail)))
    return `The unit price is ${m[1]}, but the purchase order says ${m[2]}: ${m[3].replace(/^[+-]/, "")}% ${m[3].startsWith("-") ? "less" : "more"}, where up to ${m[4]}% is allowed.`;
  if (code === "not_received") return "Nothing has been received against this purchase order yet.";
  if (code === "po_not_found" && (m = /purchase order (.+) in/.exec(detail))) return `The invoice mentions purchase order ${m[1]}, but there's no such order in the ERP.`;
  if (code === "line_not_on_po" && (m = /'(.+)' is not on PO (.+)/.exec(detail))) return `“${m[1]}” isn't on purchase order ${m[2]}.`;
  if (code === "totals" && (m = /line amounts sum to (.+), plus tax (.+) makes (.+), but the total is (.+)/.exec(detail)))
    return `The lines add up to ${m[1]}, plus ${m[2]} tax makes ${m[3]}, but the invoice says the total is ${m[4]}.`;
  if (code === "duplicate") return "Same vendor and invoice number as an invoice we already have.";
  return detail.charAt(0).toUpperCase() + detail.slice(1);
}

export const lineLabel = (pageNo: number, lineNo: number, pages: number) => pages > 1 ? `Line ${lineNo}, page ${pageNo}` : `Line ${lineNo}`;
export function labelFrom(raw: string | null | undefined, pages: number): string {
  const m = /page (\d+) line (\d+)/.exec(raw ?? "");
  return m ? lineLabel(+m[1], +m[2], pages) : raw ?? "";
}

export type Proposal = { actionType: string; details: Record<string, any> } | null | undefined;

export function proposalTitle(a: Proposal, formatAmount: (minor: number, currency: string) => string): string {
  if (!a) return "No recommendation";
  if (a.actionType === "credit_memo_request") return `Ask the vendor for a ${formatAmount(a.details.amount_minor, a.details.currency)} credit`;
  const titles: Record<string, string> = {
    duplicate: "Hold as a duplicate", missing_po: "Hold until the PO is found", tax_mismatch: "Hold for a corrected invoice",
    price_variance: "Hold over the price", short_shipment: "Hold until the goods arrive",
    agent_budget_exceeded: "Hold for review (the agent ran out of time)", agent_no_proposal: "Hold for review",
  };
  return titles[a.details.reason_code] ?? "Hold for review";
}
export const proposalWhy = (a: Proposal) => (a ? a.details.reason || a.details.explanation || "" : "");

export function dueState(dueDate: string | null | undefined, today = new Date()) {
  if (!dueDate) return null;
  const start = new Date(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.round((new Date(dueDate + "T00:00:00").getTime() - start.getTime()) / 864e5);
  if (days < 0) return { tone: "bad", icon: "calendar-x", text: `Overdue by ${-days} day${days === -1 ? "" : "s"}` };
  if (days === 0) return { tone: "bad", icon: "calendar-clock", text: "Due today" };
  if (days <= 7) return { tone: "warn", icon: "calendar-clock", text: `Due in ${days} day${days === 1 ? "" : "s"}` };
  return { tone: "", icon: "calendar", text: `Due in ${days} days` };
}

/** The 3-way match as the checks it runs, each passed or failed according to the stored reasons. */
export const MATCH_CHECKS = [
  { title: "The purchase order exists", codes: ["po_missing", "po_not_found"] },
  { title: "Same vendor and currency as the purchase order", codes: ["vendor_mismatch", "currency_mismatch"] },
  { title: "Every line is on the purchase order", codes: ["line_not_on_po", "line_unreadable", "no_lines"] },
  { title: "Prices match the purchase order, within 1%", codes: ["price_variance"] },
  { title: "Quantities match what was received", codes: ["short_shipment", "not_received", "quantity_mismatch", "quantity_over_po"] },
];

const descKey = (s: string | null | undefined) => (s ?? "").toLowerCase().replace(/[^\p{L}\p{N}]+/gu, " ").trim();

type CaseLine = { pageNo: number; lineNo: number; description?: string | null; quantity?: string | null; unitPrice?: string | null;
  amount?: Money; invalidReason?: string | null };
type PoLine = { lineNo: number; description: string; quantity: string; unitPrice: string };

/** Each invoice line next to its PO line and the quantity received, and what's billed beyond what's due
 * (PO price × quantity received). Display only: the decision rules live in the API (matching.py). */
export function tieOut(lines: CaseLine[], poLines: PoLine[] | null | undefined,
                       receipts: { lines: { poLineNo: number; quantity: string }[] }[], exponent: number) {
  const received = new Map<number, number>();
  for (const r of receipts) for (const l of r.lines) received.set(l.poLineNo, (received.get(l.poLineNo) ?? 0) + Number(l.quantity));
  const unused = [...(poLines ?? [])];
  const rows = lines.map(l => {
    const index = unused.findIndex(p => descKey(p.description) === descKey(l.description));
    const po = index >= 0 ? unused.splice(index, 1)[0] : null;
    const got = po ? received.get(po.lineNo) ?? 0 : null;  // a PO line with no receipt has received nothing
    const billed = l.amount?.amountMinor ?? null;
    const due = po && got !== null && l.quantity != null ? Math.round(Math.min(Number(l.quantity), got) * Number(po.unitPrice) * 10 ** exponent) : null;
    return { line: l, po, received: got, billed, due, over: due !== null && billed !== null ? Math.max(0, billed - due) : null };
  });
  const checked = rows.some(r => r.due !== null);
  return { rows, checked, over: checked ? rows.reduce((s, r) => s + (r.over ?? 0), 0) : null };
}

export type Step = { toolName?: string | null; arguments?: any; result?: any; error?: string | null };

/** One agent tool call as [what it did, what it found]. */
export function narrate(s: Step): [string, string] {
  const r = s.result ?? {};
  if (s.error) return ["Refused", s.error];
  switch (s.toolName) {
    case "get_po": return r.found
      ? ["Found the purchase order", `PO ${r.po_number}, ${r.lines.length} line${r.lines.length > 1 ? "s" : ""}, ${r.same_vendor_as_invoice ? "same vendor as the invoice" : "issued to a different vendor"}`]
      : ["Looked up the purchase order", `No PO ${s.arguments?.po_number} in the ERP data`];
    case "get_receipts": return ["Checked goods received", `${r.receipts.length} receipt${r.receipts.length === 1 ? "" : "s"}: ` +
      Object.entries(r.received_per_po_line ?? {}).map(([n, q]) => `PO line ${n} × ${Number(q)}`).join(", ")];
    case "get_vendor_history": return ["Read the vendor's history", `Last ${r.recent.length} invoices; ${r.recent.filter((x: any) => x.duplicate_of).length} flagged as duplicates`];
    case "compute_variance": return ["Computed what's due", `Billed too much by ${r.total_overbilled} ${r.currency}`];
    case "draft_credit_memo_request": return ["Proposed a credit memo", `${r.amount} for ${(s.arguments?.lines ?? []).join(", ")}`];
    case "propose_hold": return ["Proposed a hold", String(s.arguments?.reason_code ?? "").replaceAll("_", " ")];
    default: return [s.toolName ?? "Step", JSON.stringify(r)];
  }
}

export const when = (iso: string | null | undefined) => iso
  ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
export const longDate = (iso: string | null | undefined) => iso
  ? new Date(iso + "T00:00:00").toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" }) : "—";
export function ago(iso: string | null | undefined): string {
  if (!iso) return "";
  const s = (Date.now() - new Date(iso).getTime()) / 1000;
  return s < 60 ? "just now" : s < 3600 ? `${Math.round(s / 60)} min ago` : s < 86400 ? `${Math.round(s / 3600)} h ago` : `${Math.round(s / 86400)} days ago`;
}
export const num = (s: string | number | null | undefined) => (s == null ? "—" : String(Number(s)));
export const moneyOf = (m: Money, fmt: (minor: number, currency: string) => string) => (m ? fmt(m.amountMinor, m.currency) : "—");
