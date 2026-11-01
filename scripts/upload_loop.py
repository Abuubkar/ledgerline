"""Keep uploading invoices and listing them, and count anything that goes wrong: the traffic a live migration
has to survive (docs/migrations.md).

Uploads one generated invoice every --interval seconds through the typed client and reads the first page of
the list after each one. Stops after --seconds or when the file given by --stop-file appears, waits for every
upload to reach a final status, and prints what happened. A refused connection (the API restarting during a
deploy) is retried and counted separately from errors.
Usage: uv run python scripts/upload_loop.py [--seconds 600] [--interval 0.5] [--stop-file PATH]
"""

import argparse
import subprocess
import sys
import tempfile
import time
import uuid
from collections import Counter
from pathlib import Path

import httpx

from ledgerline_client import Client
from ledgerline_client.api.default import get_invoice, list_invoices, upload_invoices
from ledgerline_client.models import UploadInvoicesBody
from ledgerline_client.types import File

REPO = Path(__file__).resolve().parents[1]
FINAL = {"extracted", "partially_extracted", "exception", "failed"}


def call(fn, retries: Counter, **kwargs):
    """The response, retrying while the API refuses connections (a restart), for up to 30 s."""
    deadline = time.monotonic() + 30
    while True:
        try:
            return fn(**kwargs)
        except httpx.ConnectError:
            retries["connection refused"] += 1
            if time.monotonic() > deadline:
                raise
            time.sleep(0.2)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--interval", type=float, default=0.5)
    parser.add_argument("--stop-file", type=Path)
    parser.add_argument("--api", default="http://localhost:8000")
    args = parser.parse_args()
    tag = f"live{int(time.time())}"
    client = Client(base_url=args.api, timeout=httpx.Timeout(30))
    errors, retries, uploaded = Counter(), Counter(), []

    with tempfile.TemporaryDirectory() as tmp:
        count = int(args.seconds / args.interval) + 1
        subprocess.run([sys.executable, str(REPO / "scripts/make_invoice.py"), "--random", str(count), "--seed", tag,
                        "--tag", tag, tmp], check=True, capture_output=True)
        pdfs = sorted(Path(tmp).glob(f"{tag}-*.pdf"))
        started = time.monotonic()
        print(f"run {tag}: uploading every {args.interval}s", flush=True)
        for n, pdf in enumerate(pdfs, start=1):
            if time.monotonic() - started > args.seconds or (args.stop_file and args.stop_file.exists()):
                break
            body = UploadInvoicesBody(files=[File(payload=pdf.open("rb"), file_name=pdf.name, mime_type="application/pdf")])
            response = call(upload_invoices.sync_detailed, retries, client=client, body=body,
                            idempotency_key=str(uuid.uuid4()))
            if response.status_code == 202:
                uploaded.append(str(response.parsed.id))
            else:
                errors[f"upload HTTP {response.status_code}"] += 1
                print(f"  upload {pdf.name}: HTTP {response.status_code} {response.content[:200]!r}", flush=True)
            listed = call(list_invoices.sync_detailed, retries, client=client, limit=5)
            if listed.status_code != 200:
                errors[f"list HTTP {listed.status_code}"] += 1
                print(f"  list: HTTP {listed.status_code} {listed.content[:200]!r}", flush=True)
            if n % 100 == 0:
                print(f"  {n} uploads, {sum(errors.values())} errors, {sum(retries.values())} refused connections "
                      f"after {time.monotonic() - started:.0f}s", flush=True)
            time.sleep(args.interval)

    print(f"stopped after {len(uploaded)} uploads; waiting for extraction...", flush=True)
    statuses, deadline = Counter(), time.monotonic() + 600
    pending = set(uploaded)
    while pending and time.monotonic() < deadline:
        for invoice_id in list(pending):
            invoice = call(get_invoice.sync_detailed, retries, client=client, invoice_id=invoice_id)
            if invoice.status_code != 200:
                errors[f"get HTTP {invoice.status_code}"] += 1
                pending.discard(invoice_id)
            elif invoice.parsed.status.value in FINAL:
                statuses[invoice.parsed.status.value] += 1
                pending.discard(invoice_id)
        time.sleep(2)

    print(f"\nuploads accepted: {len(uploaded)}")
    print(f"final statuses: {dict(statuses)}; still not final: {len(pending)}")
    print(f"errors: {dict(errors) or 0}")
    print(f"refused connections (API restarts), retried: {sum(retries.values())}")
    sys.exit(1 if errors or pending or statuses["failed"] else 0)


if __name__ == "__main__":
    main()
