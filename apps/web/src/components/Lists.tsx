"use client";
// The lists a reviewer moves through (the exception queue, all invoices by status), kept across pages so the case
// file can say "Case 3 of 12+" and J/K can step to the next case, fetching the next page by its cursor when needed.
import { createContext, useCallback, useContext, useRef, useState, type MutableRefObject, type ReactNode } from "react";
import { useClient } from "urql";
import { ExceptionsQueueQuery, InvoicesQuery } from "@/lib/queries";
import type { ListInvoiceFieldsFragment } from "@/gql/graphql";

export const PAGE_SIZE = 12;
export type ListState = { items: ListInvoiceFieldsFragment[]; endCursor: string | null; hasNext: boolean; loading: boolean; error?: string };
type CaseActions = { approve?: () => void; reject?: () => void };
type ListsValue = {
  lists: Record<string, ListState>;
  load: (key: string, more?: boolean) => Promise<ListState>;
  /** Which "all invoices" list a case was opened from, so J/K follow that list. */
  invoicesKey: string;
  setInvoicesKey: (key: string) => void;
  /** Set by the open case file, so keyboard shortcuts can decide on it. */
  caseActions: MutableRefObject<CaseActions>;
};

const ListsContext = createContext<ListsValue | null>(null);
export const listKey = (view: "exceptions" | "invoices", status = "") => (view === "exceptions" ? "exceptions" : `invoices:${status}`);

export function ListsProvider({ children }: { children: ReactNode }) {
  const client = useClient();
  const [lists, setLists] = useState<Record<string, ListState>>({});
  const listsRef = useRef(lists);
  listsRef.current = lists;
  const [invoicesKey, setInvoicesKey] = useState("invoices:");
  const caseActions = useRef<CaseActions>({});

  const load = useCallback(async (key: string, more = false) => {
    const current = listsRef.current[key] ?? { items: [], endCursor: null, hasNext: true, loading: false };
    const update = (next: ListState) => { listsRef.current = { ...listsRef.current, [key]: next }; setLists(listsRef.current); return next; };
    update({ ...current, loading: true, error: undefined });
    const after = more ? current.endCursor : null;
    const result = key === "exceptions"
      ? await client.query(ExceptionsQueueQuery, { first: PAGE_SIZE, after }, { requestPolicy: "network-only" }).toPromise()
      : await client.query(InvoicesQuery, { first: PAGE_SIZE, after, status: key.split(":")[1] || null }, { requestPolicy: "network-only" }).toPromise();
    const connection = result.data && ("exceptionsQueue" in result.data ? result.data.exceptionsQueue : result.data.invoices);
    if (!connection) return update({ ...current, loading: false, error: result.error?.message ?? "Couldn't load the list" });
    const items = connection.edges.map(e => e.node);
    return update({ items: more ? [...current.items, ...items] : items, endCursor: connection.pageInfo.endCursor ?? null,
                    hasNext: connection.pageInfo.hasNextPage, loading: false });
  }, [client]);

  return <ListsContext.Provider value={{ lists, load, invoicesKey, setInvoicesKey, caseActions }}>{children}</ListsContext.Provider>;
}

export function useLists() {
  const value = useContext(ListsContext);
  if (!value) throw new Error("useLists needs a ListsProvider");
  return value;
}
