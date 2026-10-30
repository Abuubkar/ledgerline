"""Slice 3b's real-model check: the edge-case invoices from `make_invoice.py --scenarios`, end to end.

Uploads each scenario (or finds the stored original on a rerun), waits for a terminal status, and compares the
outcome and header fields with what the scenario should produce. Prints per-page source and model time.
Usage: uv run python scripts/check_scenarios.py [scenarios_dir]
"""

import json
import sys
import tempfile
import time
import uuid
from pathlib import Path

import httpx

API = "http://localhost:8000"
REPO = Path(__file__).resolve().parents[1]
DONE = {"extracted", "partially_extracted", "exception", "failed"}
FIELDS = ["vendor_name", "vendor_tax_id", "invoice_number", "invoice_date", "due_date", "currency",
          "subtotal_minor", "tax_minor", "total_minor"]

EXPECTED = {
    "scenario-dense-middle": {"status": "partially_extracted", "pages": ["extracted", "failed", "extracted"],
                              "repair": False},
    "scenario-blank-middle": {"status": "extracted", "pages": ["extracted", "blank", "extracted"], "repair": False},
    "scenario-misprinted-total": {"status": "exception", "pages": ["extracted"], "repair": True},
    "scenario-scanned": {"status": "extracted", "pages": ["extracted"], "repair": False, "source": "image"},
}


def upload(pdf: Path) -> dict:
    response = httpx.post(f"{API}/v1/invoices", headers={"Idempotency-Key": str(uuid.uuid4())},
                          files=[("files", (pdf.name, pdf.read_bytes(), "application/pdf"))], timeout=60)
    if response.status_code == 409 and response.json().get("code") == "duplicate_invoice":
        return httpx.get(f"{API}{response.json()['duplicate_of_url']}").json()  # a rerun: check the original
    response.raise_for_status()
    return response.json()


def wait(invoice_id: str, timeout: float = 900) -> dict:
    deadline = time.monotonic() + timeout
    while (invoice := httpx.get(f"{API}/v1/invoices/{invoice_id}").json())["status"] not in DONE:
        if time.monotonic() > deadline:
            raise SystemExit(f"{invoice_id} still {invoice['status']} after {timeout}s")
        time.sleep(2)
    return invoice


def flatten(invoice: dict) -> dict:
    out = {name: invoice.get(name) for name in FIELDS}
    for name in ("subtotal", "tax", "total"):
        out[f"{name}_minor"] = (invoice.get(name) or {}).get("amount_minor")
    return out


def main() -> None:
    if len(sys.argv) > 1:
        folder = Path(sys.argv[1])
    else:
        folder = Path(tempfile.mkdtemp())
        import subprocess

        subprocess.run([sys.executable, str(REPO / "scripts/make_invoice.py"), "--scenarios", str(folder)], check=True)

    all_ok = True
    for slug, expected in EXPECTED.items():
        pdf = folder / f"{slug}.pdf"
        gold = json.loads(pdf.with_suffix(".json").read_text())
        started = time.monotonic()
        invoice = wait(upload(pdf)["id"])
        got = flatten(invoice)
        page_statuses = [p["status"] for p in invoice["pages"]]
        checks = {
            "status": (invoice["status"], expected["status"]),
            "pages": (page_statuses, expected["pages"]),
            "repair_attempted": (invoice["repair_attempted"], expected["repair"]),
        }
        if "source" in expected:
            checks["source"] = (invoice["pages"][0]["source"], expected["source"])
        wrong_fields = [f for f in FIELDS if got[f] != gold[f]]

        print(f"\n{slug}  ({time.monotonic() - started:.0f}s wall-clock, model {invoice['llm_ms']} ms total)")
        for name, (actual, want) in checks.items():
            ok = actual == want
            all_ok &= ok
            print(f"  {name:17} {str(actual):45} want {str(want):30} {'ok' if ok else 'NO'}")
        for p in invoice["pages"]:
            print(f"  page {p['page_no']}: {p['status']:9} via {p['source']:5} model {p['llm_ms']} ms"
                  + (f"  error={p['error_code']}" if p["error_code"] else ""))
        print(f"  lines: {len(invoice['lines'])} on pages {sorted({l['page_no'] for l in invoice['lines']})}")
        print(f"  header fields vs gold: {len(FIELDS) - len(wrong_fields)}/{len(FIELDS)} right"
              + (f"; wrong: {[(f, got[f], gold[f]) for f in wrong_fields]}" if wrong_fields else ""))
        if invoice["invalid_fields"]:
            print(f"  invalid_fields: {invoice['invalid_fields']}")
    print("\nall scenario checks passed" if all_ok else "\nSOME SCENARIO CHECKS FAILED")
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
