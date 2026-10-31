"""A stand-in for the company's ERP: purchase orders and goods receipts behind the kind of API real ERPs have.

- Opaque cursors, at most 100 records a page, oldest change first ((updated_at, erp_id) ascending), so a
  record changed during a walk shows up again later in the same walk.
- `updated_since` returns only records changed at or after that time (an incremental sync).
- A cursor expires `cursor_ttl_s` after it was issued: 410 Gone, and the client has to start a new walk.
- Faults on demand: a share of requests answer 429 with Retry-After, and every request can be slowed down.

The data is the JSON file scripts/seed.py writes (ERP_DATASET), so the ERP serves the POs that the seeded
invoices cite. Not part of Ledgerline: it imports nothing from it.
Run: ERP_DATASET=data/erp/dataset.json uv run uvicorn ledgerline_erp_mock.main:app --port 8100
"""

import asyncio
import base64
import binascii
import bisect
import json
import os
import random
import time
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

RESOURCES = {"purchase-orders": "purchase_orders", "receipts": "receipts"}
PAGE_CAP = 100


class Faults(BaseModel):
    error_rate: float = float(os.environ.get("ERP_ERROR_RATE", "0"))  # share of requests answered with 429
    retry_after_s: int = int(os.environ.get("ERP_RETRY_AFTER_S", "1"))
    latency_ms: int = int(os.environ.get("ERP_LATENCY_MS", "0"))  # each request waits up to this long
    cursor_ttl_s: float = float(os.environ.get("ERP_CURSOR_TTL_S", "300"))


def _problem(status: int, title: str, detail: str, headers: dict | None = None) -> JSONResponse:
    return JSONResponse({"title": title, "status": status, "detail": detail}, status_code=status,
                        headers=headers, media_type="application/problem+json")


def _position(record: dict) -> tuple[datetime, str]:
    return datetime.fromisoformat(record["updated_at"]), record["erp_id"]


def _encode(cursor: dict) -> str:
    return base64.urlsafe_b64encode(json.dumps(cursor).encode()).decode().rstrip("=")


def _decode(cursor: str) -> dict:
    return json.loads(base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)))


def create_app(dataset: dict | None = None, faults: Faults | None = None, seed: int | None = None) -> FastAPI:
    app = FastAPI(title="erp-mock")
    app.state.faults = faults or Faults()
    app.state.rng = random.Random(seed)
    app.state.requests = []  # (path, query, status) of every list request, for tests and the sync demo

    def load(data: dict | None) -> None:
        if data is None:
            path = Path(os.environ.get("ERP_DATASET", "data/erp/dataset.json"))
            data = json.loads(path.read_text()) if path.exists() else {}
        app.state.records = {key: sorted(data.get(key, []), key=_position) for key in RESOURCES.values()}
        app.state.positions = {key: [_position(r) for r in rows] for key, rows in app.state.records.items()}

    load(dataset)

    async def list_records(resource: str, request: Request, limit: int, cursor: str | None,
                           updated_since: datetime | None):
        faults: Faults = app.state.faults
        if faults.latency_ms:
            await asyncio.sleep(app.state.rng.uniform(0, faults.latency_ms) / 1000)
        response = _page(resource, limit, cursor, updated_since, faults)
        app.state.requests.append((request.url.path, dict(request.query_params), response.status_code))
        return response

    def _page(resource: str, limit: int, cursor: str | None, updated_since: datetime | None,
              faults: Faults) -> JSONResponse:
        if app.state.rng.random() < faults.error_rate:
            return _problem(429, "Too many requests", "rate limit exceeded",
                            headers={"Retry-After": str(faults.retry_after_s)})
        after = None
        if cursor is not None:
            try:
                state = _decode(cursor)
            except (ValueError, binascii.Error):
                return _problem(400, "Invalid cursor", "the cursor is not one this ERP issued")
            if state.get("resource") != resource:
                return _problem(400, "Invalid cursor", "the cursor belongs to another list")
            if time.time() - state["issued_at"] > faults.cursor_ttl_s:
                return _problem(410, "Cursor expired", "start a new walk, with updated_since to resume")
            updated_since = datetime.fromisoformat(state["since"]) if state["since"] else None
            after = (datetime.fromisoformat(state["after"][0]), state["after"][1])

        key = RESOURCES[resource]
        rows, positions = app.state.records[key], app.state.positions[key]
        start = bisect.bisect_right(positions, after) if after else 0
        if updated_since is not None:
            start = max(start, bisect.bisect_left(positions, (updated_since, "")))
        page = rows[start:start + limit]
        more = start + limit < len(rows)
        next_cursor = _encode({
            "resource": resource, "since": updated_since.isoformat() if updated_since else None,
            "after": [page[-1]["updated_at"], page[-1]["erp_id"]], "issued_at": time.time(),
        }) if page and more else None
        return JSONResponse({"data": page, "next_cursor": next_cursor})

    @app.get("/erp/purchase-orders")
    async def purchase_orders(request: Request, limit: int = Query(PAGE_CAP, ge=1, le=PAGE_CAP),
                              cursor: str | None = None, updated_since: datetime | None = None):
        return await list_records("purchase-orders", request, limit, cursor, updated_since)

    @app.get("/erp/receipts")
    async def receipts(request: Request, limit: int = Query(PAGE_CAP, ge=1, le=PAGE_CAP),
                       cursor: str | None = None, updated_since: datetime | None = None):
        return await list_records("receipts", request, limit, cursor, updated_since)

    # Test controls, not part of the imitated ERP.
    @app.put("/erp/admin/faults")
    async def set_faults(new: Faults) -> Faults:
        app.state.faults = new
        return new

    @app.post("/erp/admin/reload")
    async def reload() -> dict:
        load(None)
        return await counts()

    @app.get("/erp/admin/counts")
    async def counts() -> dict:
        return {resource: len(app.state.records[key]) for resource, key in RESOURCES.items()}

    return app


app = create_app()
