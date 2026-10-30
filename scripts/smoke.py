"""End-to-end smoke test against the running API, using only the generated typed client for REST.

Uploads the 3 samples in one request, retries with the same key, uploads one sample under a new key (a
duplicate), pages through the list 2 at a time, then checks that GraphQL returns the same first page.
Usage: uv run python scripts/smoke.py [api_base]
"""

import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

import httpx
from ledgerline_client import Client
from ledgerline_client.api.default import list_invoices, upload_invoices
from ledgerline_client.models import Invoice, InvoicePage, MultiStatus, Problem, UploadInvoicesBody
from ledgerline_client.types import File

SAMPLES = Path(__file__).resolve().parents[1] / "samples"


def files(*names: str) -> UploadInvoicesBody:
    return UploadInvoicesBody(
        files=[File(payload=(SAMPLES / n).open("rb"), file_name=n, mime_type="application/pdf") for n in names]
    )


def timed_upload(client: Client, body: UploadInvoicesBody, key: uuid.UUID):
    started = time.perf_counter()
    response = upload_invoices.sync_detailed(client=client, body=body, idempotency_key=str(key))
    return response, time.perf_counter() - started


def describe(parsed) -> str:
    if isinstance(parsed, MultiStatus):
        return ", ".join(
            f"{r.filename}→{r.status}" + (f" ({r.problem.code.value})" if r.problem else f" ({r.invoice.status.value}, {r.invoice.llm_ms} ms)")
            for r in parsed.results
        )
    if isinstance(parsed, Invoice):
        return f"{parsed.original_filename} {parsed.status.value}"
    if isinstance(parsed, Problem):
        return f"problem {parsed.code.value}: {parsed.detail}"
    return repr(parsed)


def main() -> None:
    api = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    # Extraction is synchronous (~25 s per invoice), so the default 5 s timeout is far too short.
    client = Client(base_url=api, timeout=httpx.Timeout(600))
    samples = ("inv-001.pdf", "inv-002.pdf", "inv-003.pdf")
    key = uuid.uuid4()

    print(f"1. Bulk upload of {len(samples)} samples, Idempotency-Key {key}")
    first, took = timed_upload(client, files(*samples), key)
    print(f"   HTTP {first.status_code} in {took:.1f}s: {describe(first.parsed)}")

    print("2. Same request, same key (a client retry)")
    second, took = timed_upload(client, files(*samples), key)
    replayed = second.headers.get("idempotent-replayed")
    print(f"   HTTP {second.status_code} in {took * 1000:.0f} ms, Idempotent-Replayed={replayed}, "
          f"identical body: {second.content == first.content or json.loads(second.content) == json.loads(first.content)}")

    print("3. One sample again under a new key (same content, new request)")
    third, took = timed_upload(client, files(samples[0]), uuid.uuid4())
    print(f"   HTTP {third.status_code} in {took * 1000:.0f} ms: {describe(third.parsed)}")
    if isinstance(third.parsed, Problem):
        print(f"   duplicate_of_url: {third.parsed.duplicate_of_url}")

    print("4. Page through the list, 2 at a time")
    cursor, rest_first_page, page_no = None, None, 0
    while True:
        response = list_invoices.sync_detailed(client=client, limit=2, cursor=cursor) if cursor else list_invoices.sync_detailed(client=client, limit=2)
        page = response.parsed
        assert isinstance(page, InvoicePage), describe(page)
        page_no += 1
        rest_first_page = rest_first_page or [str(i.id) for i in page.data]
        print(f"   page {page_no}: " + ", ".join(f"{i.original_filename} ({i.status.value})" for i in page.data))
        cursor = page.next_cursor
        if not cursor:
            break

    print("5. GraphQL: first page of invoices")
    query = "{ invoices(first: 2) { edges { node { id originalFilename total { amountMinor currency } } } pageInfo { hasNextPage } } }"
    request = urllib.request.Request(f"{api}/graphql", data=json.dumps({"query": query}).encode(),
                                     headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        edges = json.load(response)["data"]["invoices"]["edges"]
    for edge in edges:
        node = edge["node"]
        total = node["total"]
        print(f"   {node['originalFilename']}: total {total['amountMinor']} {total['currency']}" if total else f"   {node['originalFilename']}: no total")
    print(f"   same ids as REST page 1: {[e['node']['id'] for e in edges] == rest_first_page}")


if __name__ == "__main__":
    main()
