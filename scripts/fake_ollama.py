"""A stand-in for Ollama's /api/chat, for load and chaos tests where a real model would take hours.

It reads the header fields out of the invoice text in the prompt (our generated invoices have a fixed layout),
so its answers are consistent, and it fails a configurable share of calls with HTTP 503 like an overloaded
model server. Not a model: never use it to judge extraction quality.

Run: FAIL_RATE=0.15 uv run uvicorn scripts.fake_ollama:app --port 11435
"""

import json
import os
import random
import re
import threading
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

FAIL_RATE = float(os.environ.get("FAIL_RATE", "0.15"))
LATENCY_S = float(os.environ.get("LATENCY_S", "0.2"))

app = FastAPI(title="fake-ollama")
_lock = threading.Lock()
stats = {"calls": 0, "failed_503": 0, "ok": 0}


def _find(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text, re.MULTILINE)
    return match.group(1).strip() if match else None


def _amount(label: str, text: str) -> tuple[str | None, str | None]:
    match = re.search(rf"^{label}\s+([A-Z]{{3}})\s+([\d,\.]+)\s*$", text, re.MULTILINE)
    return (match.group(1), match.group(2).replace(",", "")) if match else (None, None)


def read_header(text: str) -> dict:
    currency, total = _amount("Total due", text)
    _, subtotal = _amount("Subtotal", text)
    _, tax = _amount(r"Tax \(\d+%\)", text)
    first_line = text.split("--- page 1 ---", 1)[-1].strip().splitlines()[0]
    fields = {
        "vendor_name": first_line,
        "vendor_tax_id": _find(r"^(?:EIN|USt-IdNr\.|VAT No\.|Registration No\.|MWST-Nr\.):\s*(.+)$", text),
        "invoice_number": _find(r"^Invoice number\s+(.+)$", text),
        "invoice_date": _find(r"^Invoice date\s+(\d{4}-\d{2}-\d{2})", text),
        "due_date": _find(r"^Due date\s+(\d{4}-\d{2}-\d{2})", text),
        "currency": currency,
        "subtotal": subtotal,
        "tax": tax,
        "total": total,
    }
    return fields | {"field_confidence": {name: 0.99 for name in fields}}


@app.post("/api/chat")
async def chat(request: Request):
    body = await request.json()
    time.sleep(random.uniform(0, 2 * LATENCY_S))
    with _lock:
        stats["calls"] += 1
        fail = random.random() < FAIL_RATE
        stats["failed_503" if fail else "ok"] += 1
    if fail:
        return JSONResponse({"error": "server busy (fake outage)"}, status_code=503)

    prompt = "\n".join(m["content"] for m in body["messages"] if m["role"] == "user")
    content = json.dumps(read_header(prompt))
    return {
        "model": body["model"], "created_at": "2026-10-30T00:00:00Z",
        "message": {"role": "assistant", "content": content},
        "done": True, "done_reason": "stop",
        "total_duration": 1, "load_duration": 0,
        "prompt_eval_count": len(prompt) // 4, "prompt_eval_duration": 1,
        "eval_count": len(content) // 4, "eval_duration": 1,
    }


@app.get("/stats")
async def get_stats():
    return stats


@app.post("/stats/reset")
async def reset_stats():
    with _lock:
        stats.update(calls=0, failed_503=0, ok=0)
    return stats
