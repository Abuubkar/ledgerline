# Service level objective

## The promise

**99% of invoices reach a terminal status within 15 minutes of upload**, measured over 30 days.

A terminal status is one the pipeline doesn't move on from by itself:
- `matched` or `exception` after the 3-way match;
- `extracted` when there's no PO to match against;
- `partially_extracted`, or `failed` when the job is dead-lettered.

`exception` counts as done for this purpose: the invoice is in front of a person. What the person does next isn't
the pipeline's speed.

Why 15 minutes: a reviewer works through the exception queue in sessions; an invoice uploaded now should be there
for the next one. On the reference machine an invoice takes 1–2 minutes when nothing is queued, so 15 minutes leaves
room for a queue of several invoices and for retries after a short model outage.

## How it's measured

`ledgerline.invoice.duration` (Prometheus: `ledgerline_invoice_duration_seconds`) is a histogram recorded once per
invoice when it reaches a terminal status, with 900 s as a bucket edge. The ratio of slow invoices over a window is:

```promql
1 - sum(rate(ledgerline_invoice_duration_seconds_bucket{le="900"}[1h]))
  / sum(rate(ledgerline_invoice_duration_seconds_count[1h]))
```

recorded as `ledgerline:invoice_slow_ratio:rate5m`, `…rate30m`, `…rate1h` and `…rate6h` (infra/prometheus/alerts.yml).

**What it doesn't see:** an invoice that never reaches a terminal status (a job lost before it's counted) isn't in
the histogram at all. Those show up elsewhere: queue depth, dead letters, the chaos test's "lost invoices" check
(always 0 so far). A process killed with SIGKILL loses up to 15 s of unexported measurements, and Prometheus's OTLP
receiver can't count a series' very first measurement as an increase (ADR 0021). Both make the ratio slightly
optimistic in a low-traffic development setup and don't matter at volume.

## Error budget and alerts

The budget is 1% of invoices slow per 30 days. The alerts follow the multiwindow, multi-burn-rate pattern from
Google's SRE workbook. Each fires only when a long window shows the budget burning and a short window shows it's
still happening, so it stops soon after the problem does:

| Alert | Long window | Short window | Burn rate | Ratio threshold | Means | Severity |
|---|---|---|---|---|---|---|
| InvoiceSLOFastBurn | 1 h | 5 m | 14.4× | > 14.4% slow | 2% of the month's budget gone in an hour; the whole budget in about 2 days | page |
| InvoiceSLOSlowBurn | 6 h | 30 m | 6× | > 6% slow | 5% of the budget gone in 6 hours; the whole budget in about 5 days | ticket |

The runbook for both is [runbooks/invoice-slo-burn.md](runbooks/invoice-slo-burn.md). The cause alerts
(extraction slow, queue nearly full, Ollama unreachable, dead letters growing) usually fire alongside and say why.

## Where to look

Grafana's "Ledgerline / Pipeline" dashboard (http://localhost:3001 with `--profile observability`): the "Within 15
minutes" stat, and the "Upload → terminal status" panel. Its exemplar dots open the trace of a slow invoice.
