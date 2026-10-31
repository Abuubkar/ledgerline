"use client";
// One invoice as a case: who sent it and what's wrong, the agent's recommendation, lines against the purchase
// order and what was received, the 3-way match, how it was read, and the decision. Reads from GraphQL; deciding
// uses the approve/reject mutations, which answer VersionConflict when someone else decided first.
import { useEffect, useState } from "react";
import { useMutation, useQuery } from "urql";
import { Icon } from "./Icon";
import { useLists } from "./Lists";
import { Abbr, Hint } from "./Tip";
import { ApproveMutation, CaseQuery, RejectMutation } from "@/lib/queries";
import { exponentOf, formatMoney } from "@/lib/money";
import {
  MATCH_CHECKS, PROBLEM, STATUS, dueState, labelFrom, lineLabel, longDate, moneyOf, narrate, num, problems, proposalTitle,
  proposalWhy, sentence, tieOut, when, type Problem,
} from "@/lib/present";
import type { CaseQuery as CaseData, PendingActionFieldsFragment } from "@/gql/graphql";

type Invoice = NonNullable<CaseData["invoice"]>;
type Flash = { type: "done" | "conflict" | "missing"; action?: PendingActionFieldsFragment; mine?: "approve" | "reject" } | null;
const fmt = (minor: number, currency: string) => formatMoney(minor, currency);

export function StatusTag({ status }: { status: string }) {
  const s = STATUS[status] ?? { label: status, tone: "", icon: "circle" };
  return <span className={`tag ${s.tone}`}><Icon name={s.icon} size={13} />{s.label}</span>;
}
export function ProblemTag({ code }: { code: string }) {
  const p = PROBLEM[code] ?? PROBLEM.field;
  return <span className={`tag ${p.tone}`}><Icon name={p.icon} size={13} />{p.label}</span>;
}

export function CaseFile({ id }: { id: string }) {
  const [{ data, fetching, error }, refetch] = useQuery({ query: CaseQuery, variables: { id } });
  const [, approve] = useMutation(ApproveMutation);
  const [, reject] = useMutation(RejectMutation);
  const [note, setNote] = useState("");
  const [flash, setFlash] = useState<Flash>(null);
  const [busy, setBusy] = useState(false);
  const { caseActions } = useLists();
  const inv = data?.invoice;
  const action = inv?.pendingAction;

  async function decide(verb: "approve" | "reject") {
    if (!action || action.status !== "pending" || busy) return;
    setBusy(true);
    const variables = { id: action.id, expectedVersion: action.version, note: note || null };
    const outcome = verb === "approve" ? (await approve(variables)).data?.approvePendingAction : (await reject(variables)).data?.rejectPendingAction;
    setBusy(false);
    if (!outcome) return setFlash({ type: "missing" });
    if (outcome.__typename === "DecisionSuccess") { setFlash({ type: "done", action: outcome.pendingAction }); setNote(""); }
    else if (outcome.__typename === "VersionConflict") setFlash({ type: "conflict", action: outcome.pendingAction, mine: verb });
    else setFlash({ type: "missing" });
  }

  useEffect(() => {
    caseActions.current = action?.status === "pending" ? { approve: () => decide("approve"), reject: () => decide("reject") } : {};
    return () => { caseActions.current = {}; };
  });

  if (error) return <div className="page"><div className="notice error"><Icon name="circle-x" /><div className="grow"><b>Couldn't load this invoice</b>{error.message}</div></div></div>;
  if (fetching && !inv) return <div className="case"><div className="skeletons">{Array.from({ length: 6 }, (_, i) => <div key={i} className="skeleton" />)}</div></div>;
  if (!inv) return <div className="page"><div className="empty"><Icon name="file-question" size={28} /><div>No invoice with this id.</div></div></div>;

  const probs = problems(inv);
  const due = dueState(inv.dueDate);
  const pages = inv.pageCount ?? 1;
  const tie = tieOut(inv.lines, inv.purchaseOrder?.lines, inv.goodsReceipts, inv.currency ? exponentOf(inv.currency) : 2);
  const run = inv.agentRuns[0];
  const waiting = inv.status === "received" || inv.status === "extracting";

  return (
    <>
      <div className="case">
        <article>
          <Notice flash={flash} onReload={() => { setFlash(null); refetch({ requestPolicy: "network-only" }); }} />
          {waiting && <div className="notice info"><Icon name="loader" className="spin" /><div className="grow"><b>{STATUS[inv.status].label}</b>
            Reading usually takes under a minute per page. <button className="btn sm" onClick={() => refetch({ requestPolicy: "network-only" })}>Refresh</button></div></div>}
          <div className="who"><Icon name="building-2" /><span>{inv.vendor?.name ?? "Vendor not read yet"}</span>
            {inv.vendor?.taxId && <><span className="sep">·</span><span><Abbr term="VAT" /> <span className="num">{inv.vendor.taxId}</span></span></>}</div>
          <div className="titlerow"><h1 className="title">{inv.invoiceNumber ? `Invoice ${inv.invoiceNumber}` : inv.originalFilename}</h1>
            <StatusTag status={inv.status} />{due && <span className={`tag ${due.tone} due`}><Icon name={due.icon} size={15} />{due.text}</span>}</div>
          <p className="lede">{lede(inv, probs)}</p>
          <dl className="facts">
            <div><dt><Abbr term="PO" /> number</dt><dd className="num">{inv.poNumber ?? "None on the invoice"}</dd></div>
            <div><dt>Invoice date</dt><dd>{longDate(inv.invoiceDate)}</dd></div>
            <div className={due ? `due-${due.tone || "ok"}` : ""}><dt><Icon name={due?.icon ?? "calendar"} size={14} />Due date</dt><dd>{longDate(inv.dueDate)}</dd></div>
            <div><dt>File</dt><dd><FileLink id={inv.id} name={inv.originalFilename} /></dd></div>
          </dl>

          {inv.status === "failed" && <div className="notice error"><Icon name="circle-x" /><div className="grow"><b>Reading this invoice failed</b>
            {inv.errorDetail ?? inv.errorCode}. It's listed under dead letters, where it can be tried again.</div></div>}

          {probs.length > 0 && <section className="block"><h3>Why it was stopped</h3><ul className="problems">
            {probs.map((p, i) => <li key={i}><ProblemTag code={p.code} /><p>{sentence(p.code, p.detail)}{p.line && <span className="muted"> {labelFrom(p.line, pages)}</span>}
              {p.ref && <> <a href={`/invoices/${p.ref}`}>Open the original</a></>}</p></li>)}</ul></section>}

          {inv.lines.length > 0 && <section className="block">
            <h3>Lines{inv.purchaseOrder ? <span className="muted"> next to purchase order {inv.purchaseOrder.poNumber} and what was received</span> : inv.poNumber ? <span className="muted"> (the purchase order isn't in the <Abbr term="ERP" /> data)</span> : null}</h3>
            <table className="lines">
              <thead><tr><th>Item</th><th className="r">Billed <Hint tip="Quantity × unit price, as printed on the invoice" /></th>
                <th className="r">Ordered <Hint tip="Quantity × unit price on the purchase order" /></th><th className="r">Received</th><th className="r">Amount</th></tr></thead>
              <tbody>{tie.rows.map(r => (
                <tr key={`${r.line.pageNo}-${r.line.lineNo}`}>
                  <td><div className="item">{r.line.description ?? "(no description)"}</div><div className="muted small">{lineLabel(r.line.pageNo, r.line.lineNo, pages)}
                    {r.line.invalidReason && <> · <span className="bad">{r.line.invalidReason}</span></>}</div></td>
                  <td className="r num">{num(r.line.quantity)} × {num(r.line.unitPrice)}</td>
                  <td className={`r num ${r.po && Number(r.po.unitPrice) !== Number(r.line.unitPrice) ? "bad" : ""}`}>
                    {r.po ? `${num(r.po.quantity)} × ${num(r.po.unitPrice)}` : inv.purchaseOrder ? <span className="muted">Not on the <Abbr term="PO" /></span> : "—"}</td>
                  <td className={`r num ${r.received !== null && r.received < Number(r.line.quantity) ? "bad" : ""}`}>{r.received ?? "—"}</td>
                  <td className="r num">{moneyOf(r.line.amount, fmt)}{r.over ? <div className="bad small">{fmt(r.over, inv.currency!)} too much</div> : null}</td>
                </tr>))}</tbody>
            </table>
            <dl className="totals">
              <div><dt>Subtotal</dt><dd className="num">{moneyOf(inv.subtotal, fmt)}</dd></div>
              <div><dt>Tax</dt><dd className="num">{moneyOf(inv.tax, fmt)}</dd></div>
              <div className="grand"><dt>Total</dt><dd className="num">{moneyOf(inv.total, fmt)}</dd></div>
              {tie.over ? <div className="over"><dt>Billed too much</dt><dd className="num">{fmt(tie.over, inv.currency!)}</dd></div> : null}
            </dl>
          </section>}

          {!waiting && inv.status !== "failed" && <MatchSection inv={inv} pages={pages} />}
          {(inv.model || inv.pages.length > 0) && <HowRead inv={inv} />}

          {action && <section className="block"><h3>Decision</h3><ul className="history"><li>
            <span className={`tag ${action.status === "approved" ? "ok" : action.status === "rejected" ? "bad" : "warn"}`}>{action.status === "pending" ? "Waiting for you" : action.status === "approved" ? "Approved" : "Rejected"}</span>
            <div><b>{proposalTitle(action, fmt)}</b><div className="muted small">Proposed {when(action.createdAt)}{action.decidedAt && ` · decided ${when(action.decidedAt)}`}{action.decisionNote && ` · “${action.decisionNote}”`}</div></div>
          </li></ul></section>}
        </article>

        <aside className="aside"><h3>What the agent checked</h3>
          <p className="muted small">{run ? <>{run.steps.filter(s => s.kind === "tool").length} checks in {Math.round(run.llmMs / 1000)} seconds by the <Abbr term="AI" /> agent
            {run.guardFires ? `; ${run.guardFires} action${run.guardFires === 1 ? " was" : "s were"} refused by our rules` : ""}.</>
            : "The agent hasn't looked at this invoice. For now its runs are started by a script; there's no button for it yet."}</p>
          <ol className="chain">
            {probs.map((p, i) => <li key={`p${i}`} className="node problem"><span className="dot" /><div className="t">Why it was stopped</div><div className="s">{sentence(p.code, p.detail)}</div></li>)}
            {run?.steps.filter(s => s.kind === "tool").map(s => {
              const [title, found] = narrate(s); const end = title.startsWith("Proposed") && !s.error;
              return <li key={s.stepNo} className={`node ${s.error ? "err" : end ? "end" : "fact"}`}><span className="dot" /><div className="t">{title}</div>
                <div className="s">{end ? proposalTitle(action, fmt) : found}</div>
                <details><summary>Show the data</summary><pre>{JSON.stringify({ tool: s.toolName, asked: s.arguments, [s.error ? "error" : "answer"]: s.error ?? s.result }, null, 2)}</pre></details></li>;
            })}
          </ol>
        </aside>
      </div>

      {(inv.status === "exception" || action) && <div className="decide"><div className="in">
        <div className="what"><span>{action ? "The agent recommends" : "The agent hasn't reviewed this invoice yet"}</span><b>{proposalTitle(action, fmt)}</b></div>
        {action?.status === "pending" ? <>
          <label className="sr" htmlFor="note">Note</label>
          <input id="note" className="field" placeholder="Note for the record (optional)" value={note} onChange={e => setNote(e.target.value)} />
          <button className="btn reject" disabled={busy} onClick={() => decide("reject")}><Icon name="x" />Reject <span className="kbd">R</span></button>
          <button className="btn approve" disabled={busy} onClick={() => decide("approve")}><Icon name="check" />Approve <span className="kbd">A</span></button>
        </> : action ? <><span className={`tag ${action.status === "approved" ? "ok" : "bad"}`}>{action.status === "approved" ? "Approved" : "Rejected"}</span><span className="muted">{when(action.decidedAt)}</span></>
          : <span className="muted">Nothing to decide yet</span>}
      </div></div>}
    </>
  );
}

function lede(inv: Invoice, probs: Problem[]): string {
  const a = inv.pendingAction;
  if (a) return `${proposalTitle(a, fmt)}. ${proposalWhy(a)}`;
  const byStatus: Record<string, string> = {
    received: "Stored and waiting to be read.", extracting: "The AI model is reading this invoice now.",
    extracted: inv.poNumber ? "Read, and the numbers add up. Waiting to be compared with its purchase order." : "Read, and the numbers add up. It mentions no purchase order, so there's nothing to compare it with.",
    matched: "Read, adds up, and every line agrees with the purchase order and what was received. Ready for payment approval.",
    partially_extracted: "Some pages couldn't be read; the lines from the other pages are kept.",
    failed: "Reading this invoice failed.",
    exception: `${probs.map(p => PROBLEM[p.code]?.label ?? p.code).join(", ") || "Needs a look"}. The agent hasn't reviewed it yet.`,
  };
  return byStatus[inv.status] ?? "";
}

function Notice({ flash, onReload }: { flash: Flash; onReload: () => void }) {
  if (!flash) return null;
  if (flash.type === "conflict") return (
    <div className="notice conflict" role="alert"><Icon name="triangle-alert" /><div className="grow"><b>Someone decided this before you.</b>
      It's now {flash.action?.status} (version {flash.action?.version}){flash.action?.decisionNote ? `: “${flash.action.decisionNote}”` : ""}. Your {flash.mine === "approve" ? "approval" : "rejection"} wasn't saved.</div>
      <button className="btn sm" onClick={onReload}>Show latest</button></div>);
  if (flash.type === "missing") return <div className="notice error" role="alert"><Icon name="circle-x" /><div className="grow"><b>This proposal no longer exists.</b>Reload the invoice to see where it stands.</div></div>;
  return <div className="notice done" role="status"><Icon name="circle-check" /><div className="grow"><b>{flash.action?.status === "approved" ? "Approved" : "Rejected"}.</b>
    Recorded{flash.action?.decisionNote ? " with your note" : ""}. Nothing is sent to the vendor or the ERP yet. <span className="kbd">J</span> next case</div></div>;
}

function MatchSection({ inv, pages }: { inv: Invoice; pages: number }) {
  const intro = <p className="explain">Before an invoice is paid it's compared with two other records: the <Abbr term="PO" /> (what was ordered, and at what price) and the goods receipt (what actually arrived). That's the 3-way match.</p>;
  if (!inv.match) {
    const why = inv.status === "exception" ? "This invoice was stopped before matching, for the reason above. Invoices are matched only once they've been read without problems."
      : inv.status === "extracted" && !inv.poNumber ? "Not matched: the invoice doesn't mention a purchase order, so there's nothing to compare it with."
      : inv.status === "extracted" ? "Waiting to be matched." : "Matching happens after the invoice has been read.";
    return <section className="block"><h3>3-way match</h3>{intro}<p className="muted">{why}</p></section>;
  }
  const reasons = inv.match.reasons;
  const failed = MATCH_CHECKS.filter(c => reasons.some(r => c.codes.includes(r.code))).length;
  return (
    <section className="block">
      <h3 className="split">3-way match <span className={`tag ${failed ? "bad" : "ok"}`}>{failed ? `${failed} of ${MATCH_CHECKS.length} checks failed` : `All ${MATCH_CHECKS.length} checks passed`}</span>
        <span className="when">Checked {when(inv.match.matchedAt)}</span></h3>
      {intro}
      <ul className="checks">{MATCH_CHECKS.map(c => {
        const hits = reasons.filter(r => c.codes.includes(r.code));
        return <li key={c.title} className={hits.length ? "fail" : "pass"}><Icon name={hits.length ? "circle-x" : "circle-check"} size={15} />
          <div><b>{c.title}</b>{hits.map((h, i) => <div key={i} className="muted">{sentence(h.code, h.detail)}{h.line ? ` (${labelFrom(h.line, pages)})` : ""}</div>)}</div></li>;
      })}</ul>
    </section>
  );
}

function HowRead({ inv }: { inv: Invoice }) {
  const unsure = Object.entries((inv.fieldConfidence ?? {}) as Record<string, number>).filter(([, c]) => c < 0.9);
  return (
    <section className="block"><h3>How it was read</h3>
      <dl className="kv readkv">
        <dt>Read by</dt><dd><Abbr term="AI" /> model {inv.model ?? "—"}</dd>
        <dt><Hint tip="The version of the instructions the model was given, so results can be traced back to them.">Instructions</Hint></dt><dd className="num">{inv.promptVersion ?? "—"}</dd>
        <dt>Time taken</dt><dd>{inv.llmMs ? `${Math.round(inv.llmMs / 1000)} seconds` : "—"}</dd>
        <dt><Hint tip="If the totals didn't add up, the model is asked once to re-read the numbers. It never changes a number to make them add up.">Second look</Hint></dt>
        <dd>{inv.repairAttempted ? "Yes, the totals didn't add up the first time" : "Not needed"}</dd>
        <dt>Unsure about</dt><dd>{unsure.length ? unsure.map(([f, c]) => `${f.replaceAll("_", " ")} (${Math.round(c * 100)}% sure)`).join(", ") : "Nothing"}</dd>
      </dl>
      {inv.pages.length ? <table className="tbl"><thead><tr><th>Page</th><th>Result</th><th>Read from</th><th className="r">Time</th></tr></thead><tbody>
        {inv.pages.map(p => <tr key={p.pageNo}><td className="num">{p.pageNo}</td>
          <td>{p.status === "extracted" ? <span className="tag ok"><Icon name="check" size={13} />Read</span> : p.status === "blank" ? <span className="tag">Blank, skipped</span>
            : <><span className="tag bad">Couldn't read</span><div className="muted small">{p.errorCode}</div></>}</td>
          <td>{p.source === "image" ? <Hint tip="The page had no text in it (a scan or photo), so the AI model looked at a picture of the page.">A scanned image</Hint>
            : <Hint tip="The page contains real text, so the AI model read the words directly. This is the most reliable way.">The PDF's text</Hint>}</td>
          <td className="r num">{p.llmMs ? `${Math.round(p.llmMs / 1000)} s` : "—"}</td></tr>)}
      </tbody></table> : <p className="muted">No page details for this invoice (it was loaded by the seed script).</p>}
    </section>
  );
}

/** Opens the stored PDF in a new tab. The tab opens straight away (browsers allow new tabs only on a click),
 * then shows the file, or closes again with a note when no file is stored (seeded rows). */
function FileLink({ id, name }: { id: string; name: string }) {
  const [missing, setMissing] = useState(false);
  async function open(e: React.MouseEvent) {
    e.preventDefault();
    const tab = window.open("about:blank", "_blank");
    const url = `/v1/invoices/${id}/file`;
    const res = await fetch(url, { method: "GET" });
    if (res.ok) { if (tab) tab.location.href = url; else window.location.href = url; }
    else { tab?.close(); setMissing(true); }
  }
  return <span className="filewrap">
    <a className="filelink" href={`/v1/invoices/${id}/file`} onClick={open} title={`Open ${name} in a new tab`}><Icon name="file-text" size={14} /><span>{name}</span><Icon name="external-link" size={14} /></a>
    {missing && <span className="muted small">No stored file (loaded by the seed script).</span>}</span>;
}
