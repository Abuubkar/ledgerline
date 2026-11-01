# Results with prompt `extract-page/3` (before ADR 0017)

Kept for the record; superseded on 2026-11-01 by `extract-page/4`, which added two rules: subtotal, tax and total
only where printed (never summed from lines), and quantity from its own column (not a pack size in the description).

| Model | Header avg / lowest field | Line F1 | Agent | Page p50 / p95 | Invoices/h |
|---|---|---|---|---|---|
| gemma4:12b | 99.5% / 95.0% (vendor name) | 96.4% | 15/15 | 34 / 42 s | 74 |
| qwen3.5:9b-q4_K_M | 96.2% / 72.5% (subtotal) | 99.3% | 14/15 | 22 / 29 s | 110 |
| qwen2.5:7b-instruct | 98.8% / 92.5% (vendor name) | 97.8% | 10/15 | 14 / 18 s | 159 |

What `extract-page/4` targeted: qwen3.5 reported its own sum of a page's lines as a subtotal the page doesn't print
(10 invoices); gemma4 took the "5" in "A4 copy paper, 5 reams" as the quantity (4 invoices).

Files:
- `sweep/<model>/`: each model's REPORT.md, results.json and sweep.json. The memory figures in sweep.json were read
  after the run and are unreliable (see docs/metrics.md, slice 6c).
- `SWEEP.md`: the comparison table and recommendation as they stood.
- `REPORT.md`, `results.json`, `gemma4_12b-baseline.json`: the default model's report and the baseline.
- `cache/<model>/`: per-invoice results (fields, pages, repair calls).
- `recordings/<model>/`: every recorded extraction answer under this prompt. Agent answers stay in
  `evals/recordings/`: the agent prompt didn't change, so they're still replayed.

Nothing here is deleted: these are the reference for comparing later prompt, schema and tool changes.
