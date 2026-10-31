"use client";
import Link from "next/link";
import { useEffect, useState } from "react";
import { Icon } from "@/components/Icon";
import { ago, when } from "@/lib/present";
import { listDeadLetters, replayDeadLetter, type DeadLetter } from "@/lib/rest";

export default function DeadLettersPage() {
  const [rows, setRows] = useState<DeadLetter[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [results, setResults] = useState<Record<string, number>>({});
  const refresh = () => listDeadLetters().then(p => setRows(p.data)).catch(p => setError(p?.detail ?? "Couldn't load dead letters"));
  useEffect(() => { refresh(); }, []);

  async function replay(id: string) {
    const res = await replayDeadLetter(id);
    setResults(r => ({ ...r, [id]: res.status }));
    refresh();
  }
  const outcome: Record<number, string> = { 202: "Queued again", 200: "Already replayed", 409: "A copy was stored since", 404: "Gone" };

  return (
    <div className="page"><h1>Dead letters</h1>
      <p className="sub">Invoices whose reading gave up: a file that can't be opened, or the AI model unreachable for too long. Replaying queues the invoice again with a fresh set of retries; replaying twice does nothing the second time.</p>
      {error && <div className="notice error"><Icon name="circle-x" /><div className="grow"><b>Couldn't load dead letters</b>{error}</div></div>}
      <table className="list"><thead><tr><th>Invoice</th><th>Why it gave up</th><th className="r">Attempts</th><th>When</th><th /></tr></thead><tbody>
        {rows?.map(d => <tr key={d.id}><td><Link href={`/invoices/${d.invoice_id}`} className="num">{d.invoice_id.slice(0, 8)}…</Link></td>
          <td><span className="tag bad">{d.error_code}</span><details className="chainbox"><summary className="muted small">Error details</summary><pre>{d.exception_chain}</pre></details></td>
          <td className="r num">{d.attempts}</td><td>{when(d.created_at)}{d.replayed_at && <div className="muted small">replayed {ago(d.replayed_at)}</div>}</td>
          <td className="r">{results[d.id] && <span className="muted small">{outcome[results[d.id]] ?? results[d.id]} </span>}
            <button className="btn sm" onClick={() => replay(d.id)}><Icon name="rotate-ccw" size={14} />Replay</button></td></tr>)}
        {rows && !rows.length && <tr><td colSpan={5}><div className="empty"><Icon name="archive-x" size={28} /><div>No dead letters. Every invoice was read, or is still being retried.</div></div></td></tr>}
      </tbody></table>
    </div>
  );
}
