"""Service tests for the upload API: the real app against a real Postgres (testcontainers). Storage and the queue
are stubbed at their boundary here; the worker path is tested in test_worker_service.py."""

import asyncio
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import func, select

from ledgerline_api import service
from ledgerline_api.db import Invoice, OutboxMessage

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

SAMPLES = Path(__file__).resolve().parents[3] / "samples"


def pdf(name: str) -> tuple[str, bytes, str]:
    return (name, (SAMPLES / name).read_bytes(), "application/pdf")


@pytest.fixture
def fake_storage(monkeypatch):
    """Replaces S3. `delay` keeps a request in flight, for the concurrency test."""

    class Fake:
        delay = 0.0
        objects: dict[str, bytes] = {}

        def put(self, key, content):
            import time

            time.sleep(self.delay)
            self.objects[key] = content
            return f"s3://test/{key}"

    fake = Fake()
    fake.objects = {}
    monkeypatch.setattr(service.storage, "put", fake.put)

    async def no_backlog(session):
        return 0

    monkeypatch.setattr(service, "queue_depth", no_backlog)
    return fake


async def count_rows(client, model=Invoice) -> int:
    async with client.sessions() as session:
        return (await session.execute(select(func.count()).select_from(model))).scalar_one()


async def upload(client, files, key: uuid.UUID | None):
    headers = {"Idempotency-Key": str(key)} if key else {}
    return await client.post("/v1/invoices", files=[("files", f) for f in files], headers=headers)


async def test_upload_is_queued_with_an_outbox_job_in_the_same_transaction(client, fake_storage):
    response = await upload(client, [pdf("inv-001.pdf")], uuid.uuid4())

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "received"
    async with client.sessions() as session:
        job = (await session.execute(select(OutboxMessage))).scalar_one()
    assert job.task_name == "ledgerline.extract_invoice"
    assert job.payload == {"invoice_id": body["id"]}
    assert job.published_at is None  # the relay publishes it, not the request
    assert len(fake_storage.objects) == 1


async def test_same_key_and_files_twice_stores_one_invoice_and_replays(client, fake_storage):
    key = uuid.uuid4()
    first = await upload(client, [pdf("inv-001.pdf")], key)
    second = await upload(client, [pdf("inv-001.pdf")], key)

    assert first.status_code == second.status_code == 202
    assert second.json() == first.json()
    assert second.headers["Idempotent-Replayed"] == "true"
    assert "Idempotent-Replayed" not in first.headers
    assert await count_rows(client) == 1
    assert await count_rows(client, OutboxMessage) == 1
    assert len(fake_storage.objects) == 1


async def test_two_concurrent_requests_with_one_key_only_one_runs(client, fake_storage):
    fake_storage.delay = 0.5
    key = uuid.uuid4()
    a, b = await asyncio.gather(upload(client, [pdf("inv-001.pdf")], key), upload(client, [pdf("inv-001.pdf")], key))

    assert sorted([a.status_code, b.status_code]) == [202, 409]
    loser = a if a.status_code == 409 else b
    assert loser.headers["content-type"] == "application/problem+json"
    assert loser.json()["code"] == "request_in_progress"
    assert await count_rows(client) == 1


async def test_key_reused_with_different_files_is_422(client, fake_storage):
    key = uuid.uuid4()
    await upload(client, [pdf("inv-001.pdf")], key)
    reused = await upload(client, [pdf("inv-002.pdf")], key)
    assert reused.status_code == 422
    assert reused.json()["code"] == "idempotency_key_reused"


async def test_missing_key_is_400(client, fake_storage):
    response = await upload(client, [pdf("inv-001.pdf")], None)
    assert response.status_code == 400
    assert response.json()["code"] == "idempotency_key_missing"


async def test_same_content_under_a_new_key_is_a_duplicate_with_a_link(client, fake_storage):
    original = (await upload(client, [pdf("inv-001.pdf")], uuid.uuid4())).json()
    duplicate = await upload(client, [pdf("inv-001.pdf")], uuid.uuid4())

    assert duplicate.status_code == 409
    body = duplicate.json()
    assert body["code"] == "duplicate_invoice"
    assert body["duplicate_of"] == original["id"]
    assert body["duplicate_of_url"] == f"/v1/invoices/{original['id']}"
    assert len(fake_storage.objects) == 1  # the duplicate was never stored or queued
    assert await count_rows(client, OutboxMessage) == 1


async def test_failed_extraction_does_not_block_a_reupload(client, fake_storage):
    failed = (await upload(client, [pdf("inv-001.pdf")], uuid.uuid4())).json()
    async with client.sessions() as session:  # as if the worker dead-lettered it
        invoice = await session.get(Invoice, uuid.UUID(failed["id"]))
        invoice.status, invoice.error_code = "failed", "unreadable_pdf"
        await session.commit()

    retried = await upload(client, [pdf("inv-001.pdf")], uuid.uuid4())
    assert retried.status_code == 202
    assert retried.json()["status"] == "received"


async def test_full_queue_rejects_uploads_with_retry_after_and_stores_nothing(client, fake_storage, monkeypatch):
    from ledgerline_api.settings import settings

    async def backlog(session):
        return settings.max_queue_depth

    monkeypatch.setattr(service, "queue_depth", backlog)
    key = uuid.uuid4()
    response = await upload(client, [pdf("inv-001.pdf")], key)

    assert response.status_code == 429
    assert response.json()["code"] == "queue_full"
    assert response.headers["Retry-After"] == str(settings.upload_retry_after_s)
    assert await count_rows(client) == 0 and not fake_storage.objects
    # The key was released, so the same request succeeds once the queue drains.
    monkeypatch.setattr(service, "queue_depth", lambda session: asyncio.sleep(0, result=0))
    assert (await upload(client, [pdf("inv-001.pdf")], key)).status_code == 202


async def test_bulk_upload_reports_each_file_without_failing_the_rest(client, fake_storage):
    files = [pdf("inv-001.pdf"), ("notes.txt", b"not a pdf", "text/plain"), pdf("inv-001.pdf"), pdf("inv-002.pdf")]
    response = await upload(client, files, uuid.uuid4())

    assert response.status_code == 207
    assert [r["status"] for r in response.json()["results"]] == [202, 415, 409, 202]
    assert await count_rows(client) == 2


async def test_too_many_files_is_rejected_before_any_work(client, fake_storage):
    response = await upload(client, [pdf("inv-001.pdf")] * 51, uuid.uuid4())
    assert response.status_code == 400
    assert response.json()["code"] == "too_many_files"
    assert not fake_storage.objects


async def test_pagination_returns_every_row_once_even_with_identical_timestamps(client):
    same_moment = datetime(2026, 10, 30, 9, 0, tzinfo=UTC)
    async with client.sessions() as session:
        for i in range(7):
            # Five rows share a timestamp, as rows written in one transaction do; id must break the tie.
            created = same_moment if i < 5 else datetime(2026, 10, 30, 10 + i, 0, tzinfo=UTC)
            session.add(Invoice(status="extracted", original_filename=f"{i}.pdf", file_path="x", created_at=created))
        await session.commit()

    seen, cursor, pages = [], None, 0
    while True:
        params = {"limit": 2} | ({"cursor": cursor} if cursor else {})
        page = (await client.get("/v1/invoices", params=params)).json()
        seen += [row["id"] for row in page["data"]]
        pages += 1
        cursor = page["next_cursor"]
        if cursor is None:
            break

    assert pages == 4
    assert len(seen) == len(set(seen)) == 7
    all_rows = (await client.get("/v1/invoices", params={"limit": 100})).json()["data"]
    assert seen == [row["id"] for row in all_rows]


async def test_tampered_or_mismatched_cursor_is_400(client):
    async with client.sessions() as session:
        for i in range(3):
            session.add(Invoice(status="extracted", original_filename=f"{i}.pdf", file_path="x"))
        await session.commit()
    cursor = (await client.get("/v1/invoices", params={"limit": 1})).json()["next_cursor"]

    tampered = await client.get("/v1/invoices", params={"limit": 1, "cursor": cursor[:-2] + "AA"})
    other_filter = await client.get("/v1/invoices", params={"limit": 1, "cursor": cursor, "status": "failed"})
    assert tampered.status_code == other_filter.status_code == 400
    assert tampered.json()["code"] == other_filter.json()["code"] == "invalid_cursor"


async def test_graphql_lists_the_same_invoices_as_rest(client, fake_storage):
    for name in ("inv-001.pdf", "inv-002.pdf", "inv-003.pdf"):
        await upload(client, [pdf(name)], uuid.uuid4())
    rest = (await client.get("/v1/invoices", params={"limit": 2})).json()

    query = "query($after: String) { invoices(first: 2, after: $after) { edges { cursor node { id } } pageInfo { hasNextPage endCursor } } }"
    gql = (await client.post("/graphql", json={"query": query})).json()["data"]["invoices"]

    assert [e["node"]["id"] for e in gql["edges"]] == [row["id"] for row in rest["data"]]
    assert gql["pageInfo"]["hasNextPage"] is True
    assert gql["pageInfo"]["endCursor"] == rest["next_cursor"]
