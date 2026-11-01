# Runbook: InvoiceSLOFastBurn / InvoiceSLOSlowBurn

**Alert:** invoices are missing the 15-minute target faster than the error budget allows (docs/slo.md).
Fast burn: more than 14.4% of invoices slow over both the last hour and the last 5 minutes. Slow burn: more than 6%
over both the last 6 hours and the last 30 minutes.

## Check
1. Which part of the pipeline: almost always one of the other alerts is firing too:
   [extraction-slow](extraction-slow.md), [queue-nearly-full](queue-nearly-full.md),
   [ollama-unreachable](ollama-unreachable.md), [dead-letters-growing](dead-letters-growing.md).
2. If none is: open a slow invoice from the "Upload → terminal status" panel's exemplars. The trace shows where the
   time went (queue wait shows as the gap between the relay's publish and the worker's run span).

## Fix
Fix the underlying cause from the runbook above. The burn alert says "users are affected", the others say "why".

## Why this alert exists
docs/slo.md, ADR 0021.
