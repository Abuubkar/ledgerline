"use client";
// A case opened directly (a link, a reload) still gets its list, so "Case n of m" and J/K work. "invoices" means
// whichever all-invoices list (status filter) the reviewer last used.
import { useEffect } from "react";
import { useLists } from "./Lists";

export function EnsureList({ list }: { list: "exceptions" | "invoices" }) {
  const { lists, load, invoicesKey } = useLists();
  const key = list === "exceptions" ? "exceptions" : invoicesKey;
  useEffect(() => { if (!lists[key]) load(key); }, [key, lists, load]);
  return null;
}
