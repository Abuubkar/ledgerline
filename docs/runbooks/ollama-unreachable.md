# Runbook: OllamaUnreachable

**Alert:** `ledgerline_ollama_up` has read 0 for 2 minutes (the relay asks `GET $OLLAMA_HOST/api/version` every 15 s).
**Impact:** no extraction or agent run can finish. Jobs fail with `model_unavailable`, retry with backoff, and are
dead-lettered once their retries run out (`DeadLettersGrowing` follows). Uploads still succeed and queue up.

## Check
1. Is Ollama running? `curl -s localhost:11434/api/version` on the host (Ollama runs natively, not in Docker).
2. From inside Docker: `docker compose exec relay python -c "import httpx,os; print(httpx.get(os.environ['OLLAMA_HOST'] + '/api/version').text)"`.
   If the host works but this fails, the problem is `OLLAMA_HOST` (`WORKER_OLLAMA_HOST` in compose) or `host.docker.internal`.
3. Is the model there? `ollama list | grep gemma4:12b`. A missing model gives 404s, not "unreachable", but check while you're there.
4. Memory: on a 16 GB machine Ollama can fail to load gemma4:12b (8.7 GB) when other apps hold the memory; `ollama ps` and Activity Monitor.

## Fix
- Start Ollama (the app, or `ollama serve`), then watch the dashboard's Ollama stat go back to "up".
- Wrong host: fix `WORKER_OLLAMA_HOST` and `docker compose up -d worker relay`.
- Jobs that were dead-lettered meanwhile: replay them from the UI's Dead letters page or `POST /v1/admin/dead-letters/{id}/replay`
  once Ollama is back.

## Why this alert exists
ADR 0021. The probe is in `ledgerline_api/metrics.py` (`register_gauges`).
