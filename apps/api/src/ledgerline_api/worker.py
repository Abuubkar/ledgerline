"""Celery worker for invoice extraction, matching and the ERP sync. Run with:

    celery -A ledgerline_api.worker worker --concurrency=2
    celery -A ledgerline_api.worker beat      # exactly one: it sends sync_erp every erp_sync_interval_s

Failure handling, end to end (ADR 0009):
- TransientError: retried with exponential backoff and full jitter, up to `extraction_max_retries` times.
- PermanentError, or retries exhausted: `on_failure` writes a dead_letters row and marks the invoice failed;
  Celery then rejects the message without requeue, and RabbitMQ moves it to invoices.extract.dlq.
- Worker process or container dies mid-task: the message was never acked (acks_late), so RabbitMQ redelivers
  it. A message that keeps killing workers is dead-lettered by the queue's delivery limit (6).

Matching and the ERP sync retry TransientError the same way. A match job that still fails is rejected to
invoices.match.dlq; a failed sync is simply resumed by the next scheduled run.

Celery has no asyncio support, so each task runs the async job with asyncio.run.
"""

import asyncio
import logging
import random
import traceback
import uuid

from celery import Celery, Task
from kombu import Queue

from ledgerline_api import erp_sync, jobs
from ledgerline_api.errors import TransientError, classify
from ledgerline_api.service import EXTRACT_QUEUE, EXTRACT_TASK, MATCH_QUEUE, MATCH_TASK, SYNC_QUEUE, SYNC_TASK
from ledgerline_api.settings import settings

log = logging.getLogger("ledgerline.worker")

app = Celery("ledgerline", broker=settings.broker_url)
app.conf.update(
    # Must match infra/rabbitmq/definitions.json, which declares the queues at broker boot; the dead-letter
    # exchanges, delivery limits and overflow come from the broker policies, not from here.
    task_queues=[Queue(name, routing_key=name, queue_arguments={"x-queue-type": "quorum"})
                 for name in (EXTRACT_QUEUE, MATCH_QUEUE, SYNC_QUEUE)],
    task_default_queue=EXTRACT_QUEUE,
    task_routes={EXTRACT_TASK: {"queue": EXTRACT_QUEUE}, MATCH_TASK: {"queue": MATCH_QUEUE},
                 SYNC_TASK: {"queue": SYNC_QUEUE}},
    beat_schedule={
        # A sync not picked up before the next one is due is dropped rather than piling up behind it.
        "sync-erp": {"task": SYNC_TASK, "schedule": settings.erp_sync_interval_s,
                     "options": {"expires": settings.erp_sync_interval_s}},
    },
    task_acks_late=True,  # ack only after the task finishes, so a crash means redelivery
    task_acks_on_failure_or_timeout=False,  # a failed task is rejected without requeue → dead-lettered
    task_reject_on_worker_lost=True,  # a killed worker process requeues its message
    worker_prefetch_multiplier=1,  # one message per process: no prefetched work stuck on a dead worker
    task_time_limit=300,
    task_soft_time_limit=270,
    task_ignore_result=True,  # results live in Postgres; no result backend
    broker_transport_options={"confirm_publish": True},  # required for quorum queues
    broker_connection_retry_on_startup=True,
    # RabbitMQ 4.3+ refuses transient non-exclusive queues, which is what Celery's remote-control and event
    # queues are by default. Exclusive queues are allowed and vanish when the worker disconnects.
    control_queue_exclusive=True,
    event_queue_exclusive=True,
)


def backoff_seconds(retries: int, base: float | None = None, cap: float | None = None) -> float:
    """Exponential backoff with full jitter: a random wait in [0, min(cap, base * 2^retries)], so many jobs
    that failed together don't retry together."""
    base = settings.extraction_retry_backoff_base_s if base is None else base
    cap = settings.extraction_retry_backoff_max_s if cap is None else cap
    return random.uniform(0, min(cap, base * 2**retries))


def _retry(task: Task, exc: TransientError):
    """Retry later with backoff, or re-raise once the retries are used up."""
    if task.request.retries >= settings.extraction_max_retries:
        raise exc
    raise task.retry(exc=exc, countdown=backoff_seconds(task.request.retries), max_retries=None) from exc


class ExtractionTask(Task):
    def on_failure(self, exc, task_id, args, kwargs, einfo):
        error = classify(exc)
        chain = "".join(traceback.format_exception(exc))
        asyncio.run(jobs.dead_letter(self.name, kwargs, error, chain, attempts=self.request.retries + 1))


@app.task(bind=True, base=ExtractionTask, name=EXTRACT_TASK)
def extract_invoice(self, invoice_id: str) -> str:
    try:
        outcome = asyncio.run(jobs.extract(uuid.UUID(invoice_id), self.request.id, attempt=self.request.retries + 1))
    except TransientError as exc:
        _retry(self, exc)  # out of retries, it raises and on_failure dead-letters it
    # PermanentError propagates: on_failure dead-letters it straight away.
    return outcome.value


@app.task(bind=True, name=MATCH_TASK)
def match_invoice(self, invoice_id: str) -> str:
    try:
        return asyncio.run(jobs.match(uuid.UUID(invoice_id)))
    except TransientError as exc:
        _retry(self, exc)
    except (ConnectionError, TimeoutError) as exc:
        _retry(self, classify(exc))


# A sync with 20% rate-limited pages and slow answers takes minutes, not seconds.
@app.task(bind=True, name=SYNC_TASK, time_limit=900, soft_time_limit=870)
def sync_erp(self) -> str:
    try:
        result = asyncio.run(erp_sync.run())
    except TransientError as exc:
        _retry(self, exc)
    if result.skipped:
        log.info("sync_erp: another run holds the lock; skipped")
        return "skipped"
    for report in result.reports:
        log.info("sync_erp %s", report)
    return "; ".join(map(str, result.reports))
