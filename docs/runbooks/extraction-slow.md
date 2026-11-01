# Runbook: ExtractionSlow

**Alert:** 95th-percentile extraction attempt over 45 s for 10 minutes (`ledgerline_extraction_duration_seconds`).
**Impact:** invoices take longer to reach review; if it keeps up, the 15-minute SLO starts burning (docs/slo.md).

## Check
1. The model is almost all of it (99.5% of an extraction in the slice 8a trace). Dashboard: "Model call duration" and
   "Output tokens per second". gemma4:12b normally does 11–15 tokens/s and 34 s per page on the reference Mac.
2. Slow per token: the machine is busy or swapping (memory pressure with gemma's 8.7 GB); `ollama ps`, Activity Monitor.
3. Normal per token but more of them: longer invoices (more pages) or more repair calls. Open an exemplar on the
   extraction panel to see that invoice's trace: one `chat` span per page, plus one if a repair ran.
4. Waiting, not working: "Waiting for a model slot" high means jobs queue for `LLM_MAX_CONCURRENCY` slots; the time is
   counted in the attempt.

## Fix
- Free memory or move Ollama to a bigger machine; a smaller model is a decision (evals/SWEEP.md has the trade-offs).
- Many multi-page invoices are expected to take longer: per-page time is the better signal (docs/metrics.md).

## Why this alert exists
The plan's extraction target (ADR 0015 explains why speed isn't an eval gate); ADR 0021 for the alert.
