"use client";
// Tooltips for acronyms and jargon: shown on hover and on keyboard focus, with the expansion also spoken by
// screen readers. One floating layer, positioned next to whatever is hovered or focused.
import { useEffect, useRef, type ReactNode } from "react";
import { Icon } from "./Icon";

export const TERMS: Record<string, [string, string]> = {
  PO: ["Purchase order", "The order your company sent the vendor: what was bought, how many, and at what price."],
  ERP: ["Enterprise resource planning", "The company's accounting system, where purchase orders and goods receipts come from."],
  VAT: ["Value-added tax", "The vendor's tax registration number, printed on the invoice."],
  AI: ["Artificial intelligence", "A language model that runs on our own machine; it reads invoices and proposes actions, but never decides."],
};

export function Abbr({ term }: { term: keyof typeof TERMS }) {
  const [full, explain] = TERMS[term];
  return <abbr tabIndex={0} data-tip-title={full} data-tip={explain}>{term}<span className="sr"> ({full})</span></abbr>;
}

export function Hint({ children, tip }: { children?: ReactNode; tip: string }) {
  return <span className="hint" tabIndex={0} data-tip={tip}>{children}<Icon name="info" className="hi" size={13} />
    {!children && <span className="sr">More information</span>}</span>;
}

export function TipLayer() {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const tip = ref.current!;
    const show = (el: HTMLElement) => {
      tip.replaceChildren();
      if (el.dataset.tipTitle) tip.append(Object.assign(document.createElement("b"), { textContent: el.dataset.tipTitle }));
      tip.append(el.dataset.tip ?? "");
      tip.style.display = "block";
      const r = el.getBoundingClientRect(), w = tip.offsetWidth, h = tip.offsetHeight;
      tip.style.left = `${Math.max(8, Math.min(innerWidth - w - 8, r.left + r.width / 2 - w / 2))}px`;
      tip.style.top = `${r.bottom + 8 + h < innerHeight ? r.bottom + 8 : r.top - h - 8}px`;
    };
    const hide = () => { tip.style.display = "none"; };
    const onOver = (e: Event) => { const el = (e.target as HTMLElement).closest<HTMLElement>("[data-tip]"); if (el) show(el); else hide(); };
    document.addEventListener("mouseover", onOver);
    document.addEventListener("focusin", onOver);
    document.addEventListener("focusout", hide);
    document.addEventListener("scroll", hide, true);
    return () => { document.removeEventListener("mouseover", onOver); document.removeEventListener("focusin", onOver);
      document.removeEventListener("focusout", hide); document.removeEventListener("scroll", hide, true); };
  }, []);
  return <div ref={ref} id="tip" role="tooltip" />;
}
