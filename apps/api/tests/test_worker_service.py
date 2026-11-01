"""Service tests for the queue path: a real Celery worker consuming from a real RabbitMQ (with our boot-time
topology and dead-letter policy), Redis, SeaweedFS and Postgres in containers. Only the model is stubbed.
"""

import asyncio
import threading
import time
import uuid
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from ledgerline_api import jobs, semaphore, storage
from ledgerline_api.db import DeadLetter, ExtractionRun, Invoice
from ledgerline_api.extraction import ExtractionError, ModelCall
from ledgerline_api.normalize import ExtractedLine, ExtractedPage, RepairedInvoice, RepairedLine
from ledgerline_api.settings import settings

pytestmark = [pytest.mark.integration, pytest.mark.anyio]

REPO = Path(__file__).resolve().parents[3]
SAMPLES = REPO / "samples"


@pytest.fixture(scope="module")
def queue_stack(postgres_url):
    from testcontainers.community.redis import RedisContainer
    from testcontainers.core.container import DockerContainer
    from testcontainers.core.wait_strategies import LogMessageWaitStrategy

    rabbit = (
        DockerContainer("rabbitmq:4.4.0-management-alpine")
        .with_exposed_ports(5672, 15672)
        .with_volume_mapping(str(REPO / "infra/rabbitmq/rabbitmq.conf"), "/etc/rabbitmq/conf.d/20-ledgerline.conf")
        .with_volume_mapping(str(REPO / "infra/rabbitmq/definitions.json"), "/etc/rabbitmq/definitions.json")
        .waiting_for(LogMessageWaitStrategy("Server startup complete"))
    )
    seaweed = (
        DockerContainer("chrislusf/seaweedfs:4.51")
        .with_exposed_ports(8333)
        .with_envs(AWS_ACCESS_KEY_ID="ledgerline", AWS_SECRET_ACCESS_KEY="ledgerline-secret", S3_BUCKET="invoices")
    )
    with rabbit, seaweed, RedisContainer("redis:8.8.4-alpine") as redis_container:
        host = rabbit.get_container_host_ip()
        settings.broker_url = f"amqp://ledgerline:ledgerline@{host}:{rabbit.get_exposed_port(5672)}//"
        settings.rabbitmq_management_url = f"http://ledgerline:ledgerline@{host}:{rabbit.get_exposed_port(15672)}"
        settings.redis_url = f"redis://{redis_container.get_container_host_ip()}:{redis_container.get_exposed_port(6379)}/0"
        settings.s3_endpoint_url = f"http://{seaweed.get_container_host_ip()}:{seaweed.get_exposed_port(8333)}"
        storage._client.cache_clear()
        _wait_until(lambda: _s3_ready(), timeout=60, what="SeaweedFS S3 API")
        yield


@pytest.fixture(scope="module")
def worker(queue_stack):
    from celery.contrib.testing.worker import start_worker

    from ledgerline_api.worker import app

    app.conf.broker_url = settings.broker_url
    with start_worker(app, pool="solo", perform_ping_check=False, shutdown_timeout=20):
        yield app


@pytest.fixture
async def relay(client, worker):
    """The outbox relay, running alongside the test."""
    from ledgerline_api.relay import celery_send, publish_pending

    stop = asyncio.Event()

    async def loop():
        while not stop.is_set():
            await publish_pending(client.sessions, celery_send)
            await asyncio.sleep(0.1)

    task = asyncio.create_task(loop())
    yield
    stop.set()
    await task


def _page(page_no: int, total: str = "46.41", invoice_number: str = "INV-1") -> ExtractedPage:
    """A consistent one-line page: 39.00 + 7.41 tax = 46.41 EUR."""
    return ExtractedPage(
        vendor_name="ACME GmbH", vendor_tax_id="DE812345678", invoice_number=invoice_number, po_number=None,
        invoice_date=None, due_date=None,
        currency="EUR", subtotal=None, tax="7.41", total=total, field_confidence={"total": 0.9},
        line_items=[ExtractedLine(description=f"Item on page {page_no}", quantity="1", unit_price="39.00", amount="39.00")],
    )


@pytest.fixture
def model(monkeypatch):
    """Stands in for Ollama. `script` gives outcomes for successive page calls ('ok', 'transient', 'permanent');
    calls past its end succeed. `fail_pages` fails those page numbers permanently. `printed_total` is what
    every page reports as the total; `repair_total` is what a repair call reports (None = repair keeps it)."""

    class Fake:
        def __init__(self):
            self.script: list[str] = []
            self.fail_pages: set[int] = set()
            self.printed_total = "46.41"
            self.repair_total: str | None = None
            self.invoice_number = "INV-1"
            self.calls = 0
            self.repair_calls = 0
            self.lock = threading.Lock()  # the worker runs in another thread

        async def page(self, page_no, page_count, text, image):
            with self.lock:
                step = self.script[self.calls] if self.calls < len(self.script) else "ok"
                self.calls += 1
            if step == "transient":
                raise ExtractionError("model_unavailable", "stubbed outage")
            if step == "permanent" or page_no in self.fail_pages:
                raise ExtractionError("invalid_model_output", "stubbed bad output")
            # Only the last page prints the totals, as on a real multi-page invoice.
            total = self.printed_total if page_no == page_count else None
            result = _page(page_no, total=total or "0", invoice_number=self.invoice_number)
            if not total:
                result = result.model_copy(update={"total": None, "tax": None})
            return ModelCall(result, prompt_tokens=10, output_tokens=5, llm_ms=1)

        async def repair(self, texts, images, previous_json, problems):
            with self.lock:
                self.repair_calls += 1
            pages = len(texts)
            total = self.repair_total or self.printed_total
            repaired = RepairedInvoice(
                **_page(1, total=total, invoice_number=self.invoice_number).model_dump(exclude={"line_items"}),
                line_items=[RepairedLine(page=n, description=f"Item on page {n}", quantity="1", unit_price="39.00", amount="39.00")
                            for n in range(1, pages + 1)],
            )
            return ModelCall(repaired, prompt_tokens=20, output_tokens=10, llm_ms=2)

    fake = Fake()
    monkeypatch.setattr(jobs, "extract_page", fake.page)
    monkeypatch.setattr(jobs, "repair_invoice", fake.repair)
    monkeypatch.setattr(settings, "extraction_retry_backoff_base_s", 0.05)
    return fake


def three_page_pdf(tag: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    for n in range(1, 4):
        pdf.add_page()
        pdf.set_font("helvetica", size=12)
        pdf.cell(0, 10, f"Invoice {tag}, page {n} of 3")
    return bytes(pdf.output())


def _s3_ready() -> bool:
    try:
        storage._client().head_bucket(Bucket=settings.s3_bucket)
        return True
    except Exception:
        return False


def _wait_until(predicate, timeout: float, what: str) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise TimeoutError(f"timed out waiting for {what}")
        time.sleep(0.25)


async def wait_for_status(client, invoice_id: str, statuses: set[str], timeout: float = 30) -> dict:
    deadline = time.monotonic() + timeout
    while True:
        invoice = (await client.get(f"/v1/invoices/{invoice_id}")).json()
        if invoice["status"] in statuses:
            return invoice
        if time.monotonic() > deadline:
            raise TimeoutError(f"invoice {invoice_id} stuck in {invoice['status']}")
        await asyncio.sleep(0.2)


async def upload(client, name: str = "inv-001.pdf", content: bytes | None = None) -> dict:
    data = content if content is not None else (SAMPLES / name).read_bytes()
    response = await client.post(
        "/v1/invoices", files=[("files", (name, data, "application/pdf"))],
        headers={"Idempotency-Key": str(uuid.uuid4())},
    )
    assert response.status_code == 202, response.text
    return response.json()


async def runs(client, invoice_id: str) -> list[str]:
    async with client.sessions() as session:
        rows = await session.execute(
            select(ExtractionRun.outcome).where(ExtractionRun.invoice_id == uuid.UUID(invoice_id)).order_by(ExtractionRun.started_at)
        )
        return list(rows.scalars())


def dlq_depth() -> int:
    response = httpx.get(f"{settings.rabbitmq_management_url}/api/queues/%2F/invoices.extract.dlq")
    return response.json().get("messages", 0)


async def test_transient_failures_are_retried_until_one_completed_run(client, relay, model):
    model.script = ["transient", "transient"]
    invoice = await upload(client)

    done = await wait_for_status(client, invoice["id"], {"extracted", "failed"})

    assert done["status"] == "extracted"
    assert await runs(client, invoice["id"]) == ["transient_failure", "transient_failure", "completed"]
    assert model.calls == 3


async def test_permanent_failure_is_dead_lettered_and_replay_runs_once(client, relay, model):
    model.script = ["permanent"]
    dlq_before = dlq_depth()
    invoice = await upload(client)

    failed = await wait_for_status(client, invoice["id"], {"extracted", "failed"})
    # Its only page failed, so no page was extracted; the page's own reason is kept in the detail.
    assert failed["status"] == "failed" and failed["error_code"] == "no_page_extracted"
    assert "page 1: invalid_model_output" in failed["error_detail"]
    assert model.calls == 1  # permanent errors are never retried
    dead = (await client.get("/v1/admin/dead-letters")).json()["data"]
    assert len(dead) == 1 and dead[0]["invoice_id"] == invoice["id"] and dead[0]["attempts"] == 1
    # The message itself was rejected to RabbitMQ's dead-letter queue (management stats lag a little).
    await asyncio.to_thread(_wait_until, lambda: dlq_depth() == dlq_before + 1, 15, "message in DLQ")

    first = await client.post(f"/v1/admin/dead-letters/{dead[0]['id']}/replay")
    second = await client.post(f"/v1/admin/dead-letters/{dead[0]['id']}/replay")
    assert first.status_code == 202 and second.status_code == 200
    assert second.json()["replayed_at"] == first.json()["replayed_at"]

    done = await wait_for_status(client, invoice["id"], {"extracted"})
    assert done["status"] == "extracted"
    await asyncio.sleep(1)  # give a wrongly double-queued replay time to show up
    assert await runs(client, invoice["id"]) == ["permanent_failure", "completed"]
    assert model.calls == 2


async def test_one_failing_page_leaves_the_invoice_partially_extracted_with_the_other_pages_kept(client, relay, model):
    model.fail_pages = {2}
    invoice = await upload(client, "three-pages.pdf", three_page_pdf("partial"))

    done = await wait_for_status(client, invoice["id"], {"extracted", "partially_extracted", "exception", "failed"})

    assert done["status"] == "partially_extracted"
    assert [(p["page_no"], p["status"], p["error_code"]) for p in done["pages"]] == [
        (1, "extracted", None), (2, "failed", "invalid_model_output"), (3, "extracted", None),
    ]
    assert [line["page_no"] for line in done["lines"]] == [1, 3]
    assert model.repair_calls == 0  # with a page missing, a sum mismatch is expected, so no repair
    assert done["repair_attempted"] is False


async def test_totals_that_dont_add_up_get_exactly_one_repair_and_then_go_to_exception(client, relay, model):
    model.printed_total = "99.99"  # 3 lines of 39.00 + 7.41 tax is 124.41, not 99.99
    invoice = await upload(client, "three-pages.pdf", three_page_pdf("exception"))

    done = await wait_for_status(client, invoice["id"], {"extracted", "partially_extracted", "exception", "failed"})

    assert done["status"] == "exception"
    assert model.repair_calls == 1
    assert done["repair_attempted"] is True
    assert "but the total is 99.99" in done["invalid_fields"]["total"]
    assert done["total"]["amount_minor"] == 9999  # the printed number is kept, never "fixed"


async def test_a_repair_that_makes_the_totals_add_up_is_used(client, relay, model):
    model.printed_total = "99.99"
    model.repair_total = "124.41"  # the model re-reads the total correctly
    invoice = await upload(client, "three-pages.pdf", three_page_pdf("repaired"))

    done = await wait_for_status(client, invoice["id"], {"extracted", "partially_extracted", "exception", "failed"})

    assert done["status"] == "extracted"
    assert model.repair_calls == 1 and done["repair_attempted"] is True
    assert done["total"]["amount_minor"] == 12441
    assert "total" not in (done["invalid_fields"] or {})


async def test_a_second_copy_of_an_invoice_goes_to_exception_pointing_at_the_original(client, relay, model):
    terminal = {"extracted", "partially_extracted", "exception", "failed"}
    model.printed_total = "124.41"  # 3 pages of 39.00 + 7.41 tax: the totals add up
    original = await wait_for_status(client, (await upload(client, "a.pdf", three_page_pdf("copy-a")))["id"], terminal)
    model.invoice_number = "inv 0001"  # the same number, printed differently, on a different file
    copy = await wait_for_status(client, (await upload(client, "b.pdf", three_page_pdf("copy-b")))["id"], terminal)
    model.invoice_number = "INV-2"
    other = await wait_for_status(client, (await upload(client, "c.pdf", three_page_pdf("copy-c")))["id"], terminal)

    assert original["status"] == "extracted" and other["status"] == "extracted"
    assert copy["status"] == "exception"
    assert copy["invalid_fields"]["invoice_number"] == f"duplicate of invoice {original['id']}"
    assert copy["vendor"]["tax_id"] == "DE812345678" and copy["vendor_name"] == copy["vendor"]["name"] == "ACME GmbH"
    async with client.sessions() as session:
        vendor_ids = set((await session.execute(select(Invoice.vendor_id))).scalars())
        assert len(vendor_ids) == 1 and None not in vendor_ids  # one vendor, found again by its tax ID
        raw = (await session.execute(
            select(ExtractionRun.extracted_header).where(ExtractionRun.invoice_id == uuid.UUID(copy["id"]))
        )).scalar_one()
        assert raw["invoice_number"] == "inv 0001" and raw["vendor_tax_id"] == "DE812345678"


async def test_running_out_of_retries_dead_letters_the_job(client, relay, model, monkeypatch):
    monkeypatch.setattr(settings, "extraction_max_retries", 2)
    model.script = ["transient"] * 10
    invoice = await upload(client)

    failed = await wait_for_status(client, invoice["id"], {"extracted", "failed"})

    assert failed["status"] == "failed" and failed["error_code"] == "model_unavailable"
    assert await runs(client, invoice["id"]) == ["transient_failure"] * 3
    async with client.sessions() as session:
        dead = (await session.execute(select(DeadLetter))).scalar_one()
    assert dead.attempts == 3 and "model_unavailable" in dead.exception_chain


async def test_unreadable_pdf_goes_straight_to_the_dead_letter_queue(client, relay, model):
    invoice = await upload(client, "broken.pdf", b"%PDF-1.7\nthis is not really a pdf")

    failed = await wait_for_status(client, invoice["id"], {"extracted", "failed"})

    assert failed["status"] == "failed" and failed["error_code"] == "unreadable_pdf"
    assert model.calls == 0


async def test_an_abandoned_lease_is_taken_over(client, relay, model):
    """As if a worker was killed mid-job: a `running` run whose lease lapsed. The next attempt takes over."""
    from datetime import UTC, datetime, timedelta

    from ledgerline_api.service import enqueue_extraction

    invoice_id = uuid.uuid4()
    file_uri = await asyncio.to_thread(storage.put, f"{invoice_id}.pdf", (SAMPLES / "inv-002.pdf").read_bytes())
    async with client.sessions() as session:
        session.add(Invoice(id=invoice_id, status="extracting", original_filename="inv-002.pdf", file_path=file_uri))
        await session.flush()
        session.add(ExtractionRun(invoice_id=invoice_id, task_id="dead-worker", attempt=1, outcome="running",
                                  lease_until=datetime.now(UTC) - timedelta(seconds=1)))
        enqueue_extraction(session, invoice_id)
        await session.commit()

    done = await wait_for_status(client, str(invoice_id), {"extracted", "failed"})

    assert done["status"] == "extracted"
    assert await runs(client, str(invoice_id)) == ["abandoned", "completed"]


async def test_semaphore_caps_concurrency_and_frees_a_killed_holders_slot(queue_stack):
    import redis.asyncio as redis

    client = redis.from_url(settings.redis_url)
    await client.delete(semaphore.KEY)
    try:
        assert await semaphore.try_acquire(client, "a", limit=2, lease_s=1)
        assert await semaphore.try_acquire(client, "b", limit=2, lease_s=30)
        assert not await semaphore.try_acquire(client, "c", limit=2, lease_s=30)  # full

        await asyncio.sleep(1.2)  # "a" never released, like a killed worker; its lease lapses
        assert await semaphore.try_acquire(client, "c", limit=2, lease_s=30)

        await semaphore.release(client, "b")
        assert await semaphore.try_acquire(client, "d", limit=2, lease_s=30)

        # A holder that keeps renewing keeps its slot past the original lease.
        await client.delete(semaphore.KEY)
        assert await semaphore.try_acquire(client, "long-call", limit=1, lease_s=1)
        for _ in range(3):
            await asyncio.sleep(0.5)
            assert await semaphore.renew(client, "long-call", lease_s=1)
        assert not await semaphore.try_acquire(client, "other", limit=1, lease_s=1)
        # A lease that already lapsed is not revived by a late renewal.
        await asyncio.sleep(1.2)
        assert not await semaphore.renew(client, "long-call", lease_s=1)
    finally:
        await client.delete(semaphore.KEY)
        await client.aclose()


async def test_queue_depth_counts_rabbitmq_plus_unpublished_outbox_jobs(client, queue_stack):
    from ledgerline_api import service
    from ledgerline_api.db import OutboxMessage

    service._depth_cache = None
    async with client.sessions() as session:
        baseline = await service.queue_depth(session)
        assert isinstance(baseline, int)  # RabbitMQ answered (stats are sampled, so not asserted exactly)
        for _ in range(3):
            session.add(OutboxMessage(task_name="ledgerline.extract_invoice", payload={"invoice_id": str(uuid.uuid4())}))
        await session.commit()
        service._depth_cache = None
        assert await service.queue_depth(session) >= 3


async def test_the_stored_pdf_is_served_inline_and_a_missing_one_is_404(client, relay, model):
    content = (SAMPLES / "inv-002.pdf").read_bytes()
    invoice = await upload(client, "inv-002.pdf", content)
    await wait_for_status(client, invoice["id"], {"extracted", "exception", "partially_extracted", "failed"})
    response = await client.get(f"/v1/invoices/{invoice['id']}/file")
    assert response.status_code == 200 and response.content == content
    assert response.headers["content-type"] == "application/pdf"
    assert response.headers["content-disposition"] == "inline; filename*=UTF-8''inv-002.pdf"

    async with client.sessions() as session:
        seeded = Invoice(status="extracted", original_filename="seed-000001.pdf", file_path="s3://invoices/seed/000001.pdf")
        session.add(seeded)
        await session.commit()
    missing = await client.get(f"/v1/invoices/{seeded.id}/file")
    assert missing.status_code == 404 and missing.json()["title"] == "File not found"
    assert (await client.get(f"/v1/invoices/{uuid.uuid4()}/file")).json()["title"] == "Invoice not found"
