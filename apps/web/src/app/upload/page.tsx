"use client";
// Uploading invoices: POST /v1/invoices with an Idempotency-Key, then each stored invoice is followed through GraphQL
// until it's read (and matched).
import Link from "next/link";
import { useEffect, useState } from "react";
import { useQuery } from "urql";
import { StatusTag } from "@/components/CaseFile";
import { Icon } from "@/components/Icon";
import { Hint } from "@/components/Tip";
import { formatMoney } from "@/lib/money";
import { StatusQuery } from "@/lib/queries";
import { uploadInvoices, type UploadResponse } from "@/lib/rest";

const SETTLED = ["extracted", "matched", "exception", "partially_extracted", "failed"];

function LiveStatus({ id }: { id: string }) {
  const [{ data }, refetch] = useQuery({ query: StatusQuery, variables: { id }, requestPolicy: "network-only" });
  const inv = data?.invoice;
  const settled = inv && SETTLED.includes(inv.status);
  useEffect(() => {
    if (settled) return;
    const timer = setTimeout(() => refetch({ requestPolicy: "network-only" }), 2000);
    return () => clearTimeout(timer);
  });
  if (!inv) return <span className="muted">…</span>;
  return <Link href={`/invoices/${id}`} className="plain"><StatusTag status={inv.status} />{inv.invoiceNumber && <span className="muted"> {inv.invoiceNumber} · {inv.total ? formatMoney(inv.total.amountMinor, inv.total.currency) : ""}</span>}</Link>;
}

export default function UploadPage() {
  const [files, setFiles] = useState<File[]>([]);
  // Made in the browser only: a key generated during server rendering would differ from the client's.
  const [key, setKey] = useState("");
  // eslint-disable-next-line react-hooks/set-state-in-effect -- must run after hydration (see the comment above)
  useEffect(() => setKey(crypto.randomUUID()), []);
  const [last, setLast] = useState<File[] | null>(null);
  const [response, setResponse] = useState<UploadResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);

  async function send(batch: File[]) {
    setBusy(true);
    try {
      const res = await uploadInvoices(batch, key);
      setResponse(res); setLast(batch);
      if (!res.replayed) setFiles([]);
    } finally { setBusy(false); }
  }
  const add = (list: FileList | null) => list && setFiles(f => [...f, ...Array.from(list)]);

  return (
    <div className="page"><h1>Upload invoices</h1>
      <p className="sub">PDFs only, up to 50 at a time. Each is stored and queued to be read straight away; the same file twice is caught as a duplicate.</p>
      <div className={`drop ${over ? "over" : ""}`} onDragOver={e => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
           onDrop={e => { e.preventDefault(); setOver(false); add(e.dataTransfer.files); }}>
        <Icon name="upload" size={28} /><h3>Drop PDF invoices here</h3><div className="muted">or</div>
        <label className="btn" style={{ marginTop: 10 }}><Icon name="folder-open" />Choose files<input type="file" multiple accept="application/pdf" className="sr" onChange={e => add(e.target.files)} /></label>
      </div>
      {files.length > 0 && <div className="filechips">{files.map((f, n) => <span key={n} className="tag"><Icon name={f.type === "application/pdf" ? "file-text" : "file-x"} size={13} />{f.name}
        <button className="chipx" aria-label={`Remove ${f.name}`} onClick={() => setFiles(fs => fs.filter((_, i) => i !== n))}><Icon name="x" size={13} /></button></span>)}</div>}
      <div className="keyrow"><Hint tip="A one-time code sent with the upload. If the connection drops and you send the same upload again, the server recognizes it and doesn't store the files twice."><span className="muted">Idempotency-Key</span></Hint>
        <span className="code">{key}</span><button className="btn sm" onClick={() => setKey(crypto.randomUUID())}><Icon name="refresh-cw" size={14} />New key</button></div>
      <div className="actions">
        <button className="btn primary dark" disabled={!files.length || busy || !key} onClick={() => send(files)}><Icon name={busy ? "loader" : "send"} className={busy ? "spin" : ""} />Upload {files.length || ""} file{files.length === 1 ? "" : "s"}</button>
        {last && <button className="btn" disabled={busy} onClick={() => send(last)}><Icon name="repeat" />Send the last upload again (same key)</button>}
      </div>
      {response && <section className="block" style={{ marginTop: 28 }}>
        <h3>Response <span className={`http s${String(response.status)[0]}`}>{response.status}</span>
          {response.replayed && <span className="tag info"><Icon name="repeat" size={13} />Answered from the first upload; nothing stored twice</span>}
          {response.retryAfter && <span className="muted">Try again in {response.retryAfter} seconds</span>}</h3>
        <table className="list"><thead><tr><th>File</th><th>Result</th><th>Invoice now</th></tr></thead><tbody>
          {response.results.map((r, n) => <tr key={n}><td>{r.filename}</td>
            <td><span className={`http s${String(r.status)[0]}`}>{r.status}</span> {r.problem ? <><b className="w5">{r.problem.title}</b><div className="muted">{r.problem.detail}
              {r.problem.duplicate_of && <> <Link href={`/invoices/${r.problem.duplicate_of}`}>Open the original</Link></>}</div></> : "Stored and queued"}</td>
            <td>{r.invoice ? <LiveStatus id={r.invoice.id} /> : "—"}</td></tr>)}
        </tbody></table></section>}
    </div>
  );
}
