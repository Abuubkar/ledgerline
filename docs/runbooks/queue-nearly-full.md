# Runbook: QueueNearlyFull

**Alert:** the extraction queue has held more than 80% of `MAX_QUEUE_DEPTH` (default 500) ready jobs for 5 minutes.
**Impact:** at 100% uploads are refused with 429 `queue_full` (and `Retry-After`); nothing is lost, clients retry.

## Check
1. Arrivals or drain? Dashboard: "Invoices finished, per minute" against "Queue depth". The drain rate is the model:
   one call at a time on the reference machine, about 100 pages an hour.
2. Are workers consuming? `docker compose ps worker`; a stopped or stuck worker shows a queue that only grows.
3. Is the model up? [ollama-unreachable](ollama-unreachable.md).

## Fix
- A burst of uploads: let it drain; the 429 with Retry-After is the designed backpressure (ADR 0009).
- Workers down: `docker compose up -d worker`.
- Sustained load above what one model slot drains: that's capacity (more machines or a faster model), not a bug.

## Why this alert exists
ADR 0009 (backpressure), ADR 0021 (the alert).
