"""Chaos test for the extraction queue (slice 3a's Done-when check).

Uploads N generated invoices plus 3 corrupt PDFs while a stub model fails 15% of calls with HTTP 503, and kills
one of two worker containers mid-run. Then checks that nothing was lost or extracted twice, that every invoice
reached a terminal status, and that exactly the corrupt files were dead-lettered.

It runs against the dev database, so every invoice it uploads is named `chaos<timestamp>-...`, and at the end
everything from any chaos run (rows, queued jobs, stored PDFs) is deleted. `--keep` leaves this run's data in
place for debugging; the next run cleans it up.

Needs: the compose stack up (`docker compose up -d --wait`), migrations applied, the API on localhost:8000.
Usage: uv run python scripts/chaos.py [--count 200] [--fail-rate 0.15] [--keep]
"""

import argparse
import asyncio
import os
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx
from sqlalchemy import delete, func, select, text
from sqlalchemy.ext.asyncio import create_async_engine

from ledgerline_api import storage
from ledgerline_api.db import DeadLetter, ExtractionRun, Invoice, OutboxMessage
from ledgerline_api.settings import settings
from ledgerline_client import Client
from ledgerline_client.api.default import upload_invoices
from ledgerline_client.models import MultiStatus, UploadInvoicesBody
from ledgerline_client.types import File

REPO = Path(__file__).resolve().parents[1]
STUB_PORT = 11435
TERMINAL = ("extracted", "failed")
CHAOS_FILES = r"^chaos[0-9]+-"  # every chaos run's file names, from make_inputs' tag


def sh(*args: str, env: dict | None = None) -> str:
    return subprocess.run(args, cwd=REPO, check=True, capture_output=True, text=True, env=env).stdout


def compose_workers(ollama_host: str, scale: int, concurrency: int) -> None:
    env = os.environ | {"WORKER_OLLAMA_HOST": ollama_host, "LLM_MAX_CONCURRENCY": str(concurrency)}
    sh("docker", "compose", "up", "-d", "--wait", "--scale", f"worker={scale}", "worker", "relay", env=env)


def make_inputs(out: Path, tag: str, count: int) -> list[Path]:
    sh(sys.executable, "scripts/make_invoice.py", "--random", str(count), "--seed", tag, "--tag", tag, str(out))
    bad = []
    for i, content in enumerate([
        f"%PDF-1.7\ngarbage that is not a PDF body {tag}".encode(),
        b"%PDF-1.4\n" + f"1 0 obj << /Type /Catalog >> truncated {tag}".encode(),
        f"not even a PDF header {tag}".encode(),
    ]):
        path = out / f"{tag}-bad-{i}.pdf"
        path.write_bytes(content)
        bad.append(path)
    return sorted(out.glob(f"{tag}-0*.pdf")) + bad


def upload_batch(client: Client, paths: list[Path]) -> list[str]:
    body = UploadInvoicesBody(files=[File(payload=p.open("rb"), file_name=p.name, mime_type="application/pdf") for p in paths])
    response = upload_invoices.sync_detailed(client=client, body=body, idempotency_key=str(uuid.uuid4()))
    if response.status_code == 202:  # a one-file batch returns the invoice itself
        return [str(response.parsed.id)]
    if response.status_code != 207 or not isinstance(response.parsed, MultiStatus):
        raise SystemExit(f"upload failed: HTTP {response.status_code} {response.content[:300]!r}")
    rejected = [(r.filename, r.status) for r in response.parsed.results if r.status != 202]
    if rejected:
        raise SystemExit(f"unexpected per-file results: {rejected}")
    return [str(r.invoice.id) for r in response.parsed.results]


async def run_stats(tag: str) -> dict:
    engine = create_async_engine(settings.database_url)
    run_invoices = select(Invoice.id).where(Invoice.original_filename.like(f"{tag}-%"))
    async with engine.connect() as conn:
        statuses = dict((await conn.execute(
            select(Invoice.status, func.count()).where(Invoice.id.in_(run_invoices)).group_by(Invoice.status)
        )).all())
        outcomes = dict((await conn.execute(
            select(ExtractionRun.outcome, func.count()).where(ExtractionRun.invoice_id.in_(run_invoices)).group_by(ExtractionRun.outcome)
        )).all())
        duplicate_completed = (await conn.execute(text(
            "SELECT count(*) FROM (SELECT invoice_id FROM extraction_runs WHERE outcome = 'completed' "
            "AND invoice_id IN (SELECT id FROM invoices WHERE original_filename LIKE :p) "
            "GROUP BY invoice_id HAVING count(*) > 1) d"), {"p": f"{tag}-%"})).scalar_one()
        dead = (await conn.execute(
            select(Invoice.original_filename, DeadLetter.error_code).join(Invoice, Invoice.id == DeadLetter.invoice_id)
            .where(Invoice.id.in_(run_invoices))
        )).all()
    await engine.dispose()
    return {"statuses": statuses, "outcomes": outcomes, "duplicate_completed": duplicate_completed, "dead": dead}


async def clean_up() -> int:
    """Delete every chaos run's invoices with what hangs off them: runs, dead letters, queued jobs, stored PDFs.
    Pages and lines go with the invoice (ON DELETE CASCADE)."""
    engine = create_async_engine(settings.database_url)
    async with engine.begin() as conn:
        rows = (await conn.execute(
            select(Invoice.id, Invoice.file_path).where(Invoice.original_filename.regexp_match(CHAOS_FILES))
        )).all()
        ids = [row.id for row in rows]
        if ids:
            await conn.execute(delete(DeadLetter).where(DeadLetter.invoice_id.in_(ids)))
            await conn.execute(delete(ExtractionRun).where(ExtractionRun.invoice_id.in_(ids)))
            await conn.execute(delete(OutboxMessage).where(OutboxMessage.payload["invoice_id"].astext.in_([str(i) for i in ids])))
            await conn.execute(delete(Invoice).where(Invoice.id.in_(ids)))
    await engine.dispose()
    # After the commit: a PDF left behind by a failed delete is harmless; a row pointing at a missing PDF isn't.
    for row in rows:
        await asyncio.to_thread(storage.delete, row.file_path)
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=200)
    parser.add_argument("--fail-rate", type=float, default=0.15)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--keep", action="store_true", help="leave this run's invoices in the dev database")
    args = parser.parse_args()
    try:
        httpx.get("http://localhost:8000/docs", timeout=3).raise_for_status()
    except httpx.HTTPError:
        raise SystemExit("API not reachable on localhost:8000. Start it: uv run uvicorn ledgerline_api.main:app --port 8000")
    tag = f"chaos{int(time.time())}"
    started = time.monotonic()

    stub = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "scripts.fake_ollama:app", "--port", str(STUB_PORT), "--log-level", "warning"],
        cwd=REPO, env=os.environ | {"FAIL_RATE": str(args.fail_rate)},
    )
    try:
        print(f"run {tag}: stub model on :{STUB_PORT} failing {args.fail_rate:.0%} of calls; 2 workers")
        compose_workers(f"http://host.docker.internal:{STUB_PORT}", scale=2, concurrency=4)
        httpx.post(f"http://localhost:{STUB_PORT}/stats/reset")

        with tempfile.TemporaryDirectory() as tmp:
            paths = make_inputs(Path(tmp), tag, args.count)
            client = Client(base_url="http://localhost:8000", timeout=httpx.Timeout(120))
            uploaded: list[str] = []
            killed = None
            for i in range(0, len(paths), 10):
                uploaded += upload_batch(client, paths[i:i + 10])
                if killed is None and len(uploaded) >= len(paths) // 2:
                    killed = sh("docker", "compose", "ps", "-q", "worker").split()[-1]
                    sh("docker", "kill", killed)
                    print(f"killed worker container {killed[:12]} after {len(uploaded)} uploads")
        print(f"uploaded {len(uploaded)} files in {time.monotonic() - started:.1f}s; waiting for terminal statuses...")

        deadline = time.monotonic() + args.timeout
        while True:
            stats = asyncio.run(run_stats(tag))
            pending = sum(n for s, n in stats["statuses"].items() if s not in TERMINAL)
            if pending == 0 or time.monotonic() > deadline:
                break
            time.sleep(3)
        model = httpx.get(f"http://localhost:{STUB_PORT}/stats").json()
    finally:
        stub.terminate()
        # Back to the normal setup: one worker talking to the real model.
        compose_workers("http://host.docker.internal:11434", scale=1, concurrency=1)

    stored = sum(stats["statuses"].values())
    expected_dead = {p.name for p in paths if "-bad-" in p.name}
    dead_names = {name for name, _ in stats["dead"]}
    checks = [
        ("files uploaded (202)", len(uploaded), len(paths)),
        ("invoices stored", stored, len(paths)),
        ("lost invoices", len(paths) - stored, 0),
        ("not in a terminal status", sum(n for s, n in stats["statuses"].items() if s not in TERMINAL), 0),
        ("dead letters", len(stats["dead"]), 3),
        ("dead letters are exactly the corrupt files", dead_names == expected_dead, True),
        ("invoices with more than one completed run", stats["duplicate_completed"], 0),
        ("extracted", stats["statuses"].get("extracted", 0), args.count),
    ]
    print(f"\n{'check':45} {'got':>8} {'want':>8}  ok")
    for name, got, want in checks:
        print(f"{name:45} {str(got):>8} {str(want):>8}  {'yes' if got == want else 'NO'}")
    print(f"\nstatuses: {stats['statuses']}")
    print(f"extraction runs: {stats['outcomes']}")
    print(f"dead letters: {sorted(stats['dead'])}")
    print(f"stub model: {model['calls']} calls, {model['failed_503']} answered 503 ({model['failed_503'] / max(model['calls'], 1):.1%})")
    print(f"total time: {time.monotonic() - started:.1f}s")
    if args.keep:
        print(f"kept this run's invoices (file names {tag}-*); the next run without --keep deletes them")
    else:
        print(f"cleaned up {asyncio.run(clean_up())} chaos invoices from the dev database")
    sys.exit(0 if all(got == want for _, got, want in checks) else 1)


if __name__ == "__main__":
    main()
