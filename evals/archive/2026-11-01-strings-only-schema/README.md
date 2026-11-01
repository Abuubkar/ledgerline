# Results under the strings-only extraction schema (prompt `extract-page/2`)

Kept for the record; superseded on 2026-11-01 by `extract-page/3` (ADR 0016).

Until then the extraction schema allowed every amount (subtotal, tax, total, quantity, unit price, line amount) only as
a JSON string or null. Ollama constrains the answer to the schema, so a model that writes numbers unquoted could only
answer `null`. gemma4:12b took the other legal choice, a quote, and scored normally (given the choice under the new schema, it writes bare numbers too); the Qwen models don't, and lost every number:

| Model | Header avg | Lowest field | Line F1 | Agent | Page p50 / p95 |
|---|---|---|---|---|---|
| gemma4:12b | 98.8% | 95.0% | 97.8% | 15/15 | 36 / 46 s |
| qwen2.5:7b-instruct | 66.5% | 2.5% (totals) | 2.9% | 10/15 | 14 / 19 s |

A one-page probe confirmed the cause: the same qwen2.5 call with bare numbers allowed returned total 4286.4, quantity 16,
unit price 223.25. A two-case trial of qwen3.5:9b-q4_K_M showed the same empty numbers (its agent run was correct).

Files:
- `gemma4_12b-REPORT.md` / `gemma4_12b-results.json` / `gemma4_12b-baseline.json`: the 6a baseline.
- `qwen2.5_7b-instruct/`: its full dev-split report, results and sweep metadata.
- `qwen3.5_9b-q4_K_M-trial/extraction/g01.json`: the cached result of the two-case trial. Its recordings and its one
  agent result (a06, correct) were deleted before this archive rule existed; the numbers above are all that's left.
- `SWEEP.md`: the comparison table as generated.
- `recordings/<model>/`: every recorded extraction answer under this schema (qwen2.5's agent answers too). gemma4's
  agent answers stay in `evals/recordings/`, because the agent prompt didn't change and they're still replayed.
- `cache/<model>/`: the per-invoice results (fields, pages, repair calls) behind each report.

Nothing here is deleted: these are the reference for comparing later prompt, schema and tool changes.
