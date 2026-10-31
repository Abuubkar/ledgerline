import { act, renderHook, waitFor } from "@testing-library/react";
import { HttpResponse } from "msw/http";
import { useLists } from "@/components/Lists";
import { Providers, gql, server } from "@/testing";

const invoice = (n: number) => ({ __typename: "Invoice", id: `inv-${n}`, status: "exception", invoiceNumber: `INV-${n}`, originalFilename: `${n}.pdf`,
  poNumber: null, createdAt: "2026-10-31T10:00:00Z", vendor: null, total: null, invalidFields: null, match: null, pendingAction: null });

test("the queue asks for the next page with the endCursor of the page before", async () => {
  const afters: (string | null)[] = [];
  server.use(gql.query("ExceptionsQueue", ({ variables }) => {
    afters.push(variables.after ?? null);
    const first = variables.after == null;
    const nodes = first ? Array.from({ length: 12 }, (_, i) => invoice(i + 1)) : [invoice(13), invoice(14)];
    return HttpResponse.json({ data: { exceptionsQueue: { __typename: "InvoiceConnection",
      edges: nodes.map(node => ({ __typename: "InvoiceEdge", cursor: `cursor-${node.id}`, node })),
      pageInfo: { __typename: "PageInfo", hasNextPage: first, endCursor: first ? "cursor-inv-12" : "cursor-inv-14" } } } });
  }));
  const { result } = renderHook(() => useLists(), { wrapper: Providers });

  await act(() => result.current.load("exceptions"));
  await waitFor(() => expect(result.current.lists.exceptions?.items).toHaveLength(12));
  expect(result.current.lists.exceptions.hasNext).toBe(true);

  await act(() => result.current.load("exceptions", true));
  await waitFor(() => expect(result.current.lists.exceptions.items).toHaveLength(14));
  expect(afters).toEqual([null, "cursor-inv-12"]);
  expect(result.current.lists.exceptions.hasNext).toBe(false);
  expect(result.current.lists.exceptions.items.map(i => i.id).slice(-2)).toEqual(["inv-13", "inv-14"]);
});
