"use client";
// The frame around every page: the icon rail, the top bar (where you are, the command bar, the case position) and
// the command palette. Keyboard: ⌘K palette, J/K next/previous case, A/R approve/reject the open proposal.
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { Icon } from "./Icon";
import { listKey, useLists } from "./Lists";
import { TipLayer } from "./Tip";
import { formatMoney } from "@/lib/money";

type Option = { label: string; icon: string; hint?: string; group?: string; run: () => void };

export function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const search = useSearchParams();
  const { lists, load, invoicesKey, caseActions } = useLists();
  const [palette, setPalette] = useState(false);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState(0);

  const [, view, id] = pathname.split("/");
  const caseKey = view === "exceptions" ? listKey("exceptions") : invoicesKey;
  const list = id ? lists[caseKey] : undefined;
  const index = list ? list.items.findIndex(i => i.id === id) : -1;

  async function move(delta: number) {
    if (!id || !list || index < 0) return;
    let items = list.items;
    if (index + delta >= items.length && list.hasNext) items = (await load(caseKey, true)).items;
    const next = items[Math.max(0, Math.min(items.length - 1, index + delta))];
    if (next && next.id !== id) router.push(`/${view}/${next.id}`);
  }

  const options = useMemo<Option[]>(() => {
    const q = query.trim().toLowerCase();
    const go = (href: string) => () => router.push(href);
    const commands: Option[] = [
      { label: "Go to exceptions", icon: "circle-alert", run: go("/exceptions") },
      { label: "Go to all invoices", icon: "file-text", run: go("/invoices") },
      { label: "Upload invoices", icon: "upload", run: go("/upload") },
      { label: "Go to dead letters", icon: "archive-x", run: go("/dead-letters") },
      ...(caseActions.current.approve ? [{ label: "Approve proposal", icon: "check", hint: "A", run: () => caseActions.current.approve?.() },
                                          { label: "Reject proposal", icon: "x", hint: "R", run: () => caseActions.current.reject?.() }] : []),
      ...(index >= 0 ? [{ label: "Next case", icon: "chevron-down", hint: "J", run: () => move(1) },
                        { label: "Previous case", icon: "chevron-up", hint: "K", run: () => move(-1) }] : []),
    ].filter(c => !q || c.label.toLowerCase().includes(q));
    const seen = new Map(Object.values(lists).flatMap(l => l.items).map(i => [i.id, i]));
    const invoices: Option[] = q ? [...seen.values()]
      .filter(i => `${i.invoiceNumber} ${i.vendor?.name} ${i.poNumber} ${i.originalFilename}`.toLowerCase().includes(q)).slice(0, 8)
      .map(i => ({ label: `${i.invoiceNumber ?? i.originalFilename} · ${i.vendor?.name ?? ""}`, icon: "file-text",
                   hint: i.total ? formatMoney(i.total.amountMinor, i.total.currency) : "", run: go(`/invoices/${i.id}`) })) : [];
    if (/^[0-9a-f-]{36}$/.test(q)) invoices.unshift({ label: `Open invoice ${q.slice(0, 8)}…`, icon: "arrow-right", run: go(`/invoices/${q}`) });
    if (commands[0]) commands[0].group = "Commands";
    if (invoices[0]) invoices[0].group = "Invoices loaded so far";
    return [...commands, ...invoices];
  }, [query, lists, index, pathname]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette(p => !p); setQuery(""); setPicked(0); return; }
      if (palette) return;
      if ((e.target as HTMLElement).closest("input, textarea, select, [contenteditable]")) return;
      if (e.key === "j") move(1);
      if (e.key === "k") move(-1);
      if (e.key === "a") caseActions.current.approve?.();
      if (e.key === "r") caseActions.current.reject?.();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  });

  const run = (o?: Option) => { setPalette(false); setQuery(""); o?.run(); };
  const crumb = view === "exceptions" ? "Exceptions" : view === "invoices" ? (id ? null : "All invoices") : view === "upload" ? "Upload" : view === "dead-letters" ? "Dead letters" : "";
  const nav = (href: string, icon: string, tip: string) => (
    <Link href={href} className={view === href.slice(1) ? "on" : ""} aria-label={tip}><Icon name={icon} size={18} /><span className="railtip">{tip}</span></Link>
  );

  return (
    <div className="shell">
      <nav className="rail">
        <span className="mark"><Icon name="scale" size={18} /></span>
        {nav("/exceptions", "circle-alert", "Exceptions")}{nav("/invoices", "file-text", "All invoices")}
        {nav("/upload", "upload", "Upload")}{nav("/dead-letters", "archive-x", "Dead letters")}
        <span className="gap" />
        <span className="who-am-i" aria-label="Signed in as the demo reviewer"><Icon name="circle-user" size={18} /><span className="railtip">Demo reviewer · Accounts payable</span></span>
      </nav>
      <div className="main">
        <div className="bar">
          <span className="crumb">{crumb ?? <><Link href={`/invoices${invoicesKey.split(":")[1] ? `?status=${invoicesKey.split(":")[1]}` : ""}`}>All invoices</Link><Icon name="chevron-right" />Case</>}</span>
          <button className="cmd" onClick={() => { setPalette(true); setQuery(""); setPicked(0); }}>
            <Icon name="search" />Jump to an invoice or run a command<span className="kbd">⌘K</span>
          </button>
          {id && list && index >= 0 && (
            <div className="pos">Case <span className="num">{index + 1}</span> of <span className="num">{list.items.length}{list.hasNext ? "+" : ""}</span>
              <button className="btn" onClick={() => move(-1)} aria-label="Previous case"><Icon name="chevron-up" /><span className="kbd">K</span></button>
              <button className="btn" onClick={() => move(1)} aria-label="Next case"><Icon name="chevron-down" /><span className="kbd">J</span></button>
            </div>
          )}
        </div>
        <div className="work" key={pathname + search.toString()}>{children}</div>
      </div>
      {palette && (
        <div className="palette-bg" onClick={e => e.target === e.currentTarget && setPalette(false)}>
          <div className="palette" role="dialog" aria-label="Command palette">
            <input autoFocus value={query} placeholder="Jump to an invoice (number, vendor, PO, id) or run a command"
                   onChange={e => { setQuery(e.target.value); setPicked(0); }}
                   onKeyDown={e => {
                     if (e.key === "Escape") setPalette(false);
                     if (e.key === "ArrowDown") { e.preventDefault(); setPicked(p => (p + 1) % Math.max(options.length, 1)); }
                     if (e.key === "ArrowUp") { e.preventDefault(); setPicked(p => (p + options.length - 1) % Math.max(options.length, 1)); }
                     if (e.key === "Enter") run(options[picked]);
                   }} />
            <div className="opts">
              {options.length ? options.map((o, n) => (
                <div key={o.label}>{o.group && <div className="group">{o.group}</div>}
                  <button className={`opt ${n === picked ? "on" : ""}`} onClick={() => run(o)}><Icon name={o.icon} />{o.label}<span className="hint-r num">{o.hint}</span></button>
                </div>)) : <div className="group">No matches</div>}
            </div>
          </div>
        </div>
      )}
      <TipLayer />
    </div>
  );
}
