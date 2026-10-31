"use client";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect } from "react";
import { StatusTag } from "@/components/CaseFile";
import { Icon } from "@/components/Icon";
import { listKey, useLists } from "@/components/Lists";
import { Abbr } from "@/components/Tip";
import { formatMoney } from "@/lib/money";
import { ago } from "@/lib/present";

const TABS: [string, string][] = [["", "All"], ["exception", "Exception"], ["matched", "Matched"], ["extracted", "Read"], ["partially_extracted", "Partly read"],
  ["failed", "Failed"], ["received", "Received"], ["extracting", "Reading"]];

export default function InvoicesPage() {
  const status = useSearchParams().get("status") ?? "";
  const key = listKey("invoices", status);
  const { lists, load, setInvoicesKey } = useLists();
  const router = useRouter();
  const list = lists[key];
  useEffect(() => { setInvoicesKey(key); if (!list) load(key); }, [key]);

  return (
    <div className="page"><h1>All invoices</h1>
      <p className="sub">Every invoice, newest first. Open one to see its case file; <span className="kbd">J</span> <span className="kbd">K</span> then move through this list.</p>
      <div className="seg" role="tablist">{TABS.map(([s, t]) => <Link key={s} role="tab" aria-selected={s === status} className={s === status ? "on" : ""} href={s ? `/invoices?status=${s}` : "/invoices"}>{t}</Link>)}</div>
      {list?.error && <div className="notice error"><Icon name="circle-x" /><div className="grow"><b>Couldn't load invoices</b>{list.error}</div></div>}
      <table className="list"><thead><tr><th>Vendor</th><th>Invoice</th><th>Status</th><th><Abbr term="PO" /></th><th className="r">Total</th><th>Received</th></tr></thead>
        <tbody>
          {list?.items.map(i => (
            <tr key={i.id} className="row" onClick={() => router.push(`/invoices/${i.id}`)}>
              <td className="vendor"><Link href={`/invoices/${i.id}`}>{i.vendor?.name ?? i.originalFilename}</Link></td>
              <td className="num">{i.invoiceNumber ?? "—"}</td><td><StatusTag status={i.status} /></td>
              <td className="num muted">{i.poNumber ?? "—"}</td><td className="r num">{i.total ? formatMoney(i.total.amountMinor, i.total.currency) : "—"}</td>
              <td className="muted">{ago(i.createdAt)}</td>
            </tr>))}
          {list?.loading && <tr><td colSpan={6}><div className="skeletons">{Array.from({ length: 4 }, (_, n) => <div key={n} className="skeleton" />)}</div></td></tr>}
          {list && !list.loading && !list.items.length && <tr><td colSpan={6}><div className="empty"><Icon name="inbox" size={28} /><div>No invoices with this status.</div></div></td></tr>}
        </tbody></table>
      <div className="more">{list?.hasNext && !list.loading ? <button className="btn" onClick={() => load(key, true)}><Icon name="chevrons-down" />Load more</button>
        : list && !list.loading && list.items.length ? <span className="muted">End of list</span> : null}</div>
    </div>
  );
}
