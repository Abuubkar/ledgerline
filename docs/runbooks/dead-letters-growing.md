# Runbook: DeadLettersGrowing

**Alert:** more than 10 jobs dead-lettered in 15 minutes (`increase(ledgerline_dead_letters_total[15m])`).
**Impact:** those invoices are `failed` and won't move until someone replays them.

## Check
1. Which job and why: the dashboard's "Dead letters, by job" panel, then the reasons on the UI's Dead letters page or
   `GET /v1/admin/dead-letters` (each has an error code and the exception chain).
2. One cause for all of them? Usually yes:
   - `model_unavailable` / `model_timeout`: see [ollama-unreachable](ollama-unreachable.md); the model is down or overloaded.
   - `unreadable_pdf`, `no_page_extracted`: bad input from one sender; nothing to fix in Ledgerline.
   - `llm_slot_timeout`: jobs waited too long for a model slot (see the "Waiting for a model slot" panel); too much load
     for `LLM_MAX_CONCURRENCY`.
   - Anything else: open one dead letter's trace. Every trace with a dead letter is kept by tail sampling; find it in
     Jaeger by `ledgerline.invoice_id`.

## Fix
- Fix the cause, then replay: `POST /v1/admin/dead-letters/{id}/replay` (idempotent; replaying twice does nothing the second time).
- Bad input: tell the sender; leave the dead letters as the record.

## Why this alert exists
ADR 0009 (dead letters), ADR 0021 (the alert).
