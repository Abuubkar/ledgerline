import { fireEvent, render, screen } from "@testing-library/react";
import { HttpResponse } from "msw/http";
import { CaseFile } from "@/components/CaseFile";
import { Providers, gql, server } from "@/testing";

const action = (status: string, version: number, decisionNote: string | null = null) => ({
  __typename: "PendingAction", id: "pa-1", invoiceId: "inv-1", actionType: "hold", status, version, decisionNote,
  details: { reason_code: "duplicate", explanation: "Same number as INV-1." }, createdAt: "2026-10-31T10:00:00Z", decidedAt: status === "pending" ? null : "2026-11-01T09:00:00Z",
});
const invoice = {
  __typename: "Invoice", id: "inv-1", status: "exception", originalFilename: "inv-1.pdf", pageCount: 1, invoiceNumber: "OL-1155", poNumber: null,
  invoiceDate: "2026-10-01", dueDate: "2026-12-01", currency: "EUR", subtotal: null, tax: null, total: { __typename: "Money", amountMinor: 7050, currency: "EUR" },
  invalidFields: { invoice_number: "duplicate of invoice 0199aaaa-0000-7000-8000-000000000001" }, fieldConfidence: {}, errorCode: null, errorDetail: null,
  model: "gemma4:12b", promptVersion: "extract-page/2", llmMs: 30000, repairAttempted: false, createdAt: "2026-10-31T10:00:00Z",
  vendor: { __typename: "Vendor", id: "v-1", name: "Ortmann Löchel GmbH", taxId: "DE299618547" }, lines: [], pages: [], match: null,
  purchaseOrder: null, goodsReceipts: [], pendingAction: action("pending", 1), agentRuns: [],
};

test("approving after someone else decided shows the conflict, not a success", async () => {
  let sentVersion: number | undefined;
  server.use(
    gql.query("Case", () => HttpResponse.json({ data: { invoice } })),
    gql.mutation("Approve", ({ variables }) => {
      sentVersion = variables.expectedVersion;
      return HttpResponse.json({ data: { approvePendingAction: { __typename: "VersionConflict", currentVersion: 2,
        pendingAction: action("approved", 2, "Approved by M. Okafor") } } });
    }),
  );
  render(<CaseFile id="inv-1" />, { wrapper: Providers });

  fireEvent.click(await screen.findByRole("button", { name: /approve/i }));

  const banner = await screen.findByRole("alert");
  expect(banner).toHaveTextContent("Someone decided this before you.");
  expect(banner).toHaveTextContent("It's now approved (version 2): “Approved by M. Okafor”");
  expect(banner).toHaveTextContent("Your approval wasn't saved.");
  expect(sentVersion).toBe(1);  // the version the reviewer was looking at
  expect(screen.queryByText(/^Approved\.$/)).not.toBeInTheDocument();
});
