"""Upload each sample PDF to the running API and compare the extracted header with its gold JSON.

Usage: uv run python scripts/check_samples.py [samples_dir] [api_base]
Stdlib only, so it adds no dependency.
"""

import json
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

FIELDS = [
    "vendor_name", "vendor_tax_id", "invoice_number", "invoice_date", "due_date",
    "currency", "subtotal_minor", "tax_minor", "total_minor",
]


def upload(api: str, pdf: Path) -> dict:
    boundary = uuid.uuid4().hex
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"files\"; filename=\"{pdf.name}\"\r\n"
        "Content-Type: application/pdf\r\n\r\n"
    ).encode() + pdf.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    request = urllib.request.Request(
        f"{api}/v1/invoices", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "Idempotency-Key": str(uuid.uuid4())},
    )
    try:
        with urllib.request.urlopen(request, timeout=300) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        problem = json.load(exc)
        if problem.get("code") != "duplicate_invoice":
            raise SystemExit(f"{pdf.name}: HTTP {exc.code} {problem}") from None
        # Already uploaded on an earlier run: compare the stored original instead.
        with urllib.request.urlopen(f"{api}{problem['duplicate_of_url']}", timeout=30) as response:
            return json.load(response)


def flatten(invoice: dict) -> dict:
    out = {name: invoice.get(name) for name in FIELDS}
    for name in ("subtotal", "tax", "total"):
        money = invoice.get(name)
        out[f"{name}_minor"] = money["amount_minor"] if money else None
    return out


def main() -> None:
    samples = Path(sys.argv[1] if len(sys.argv) > 1 else "samples")
    api = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
    total_wrong = 0
    for pdf in sorted(samples.glob("*.pdf")):
        gold = json.loads(pdf.with_suffix(".json").read_text())
        invoice = upload(api, pdf)
        got = flatten(invoice)
        print(f"\n{pdf.name}  status={invoice['status']}  id={invoice['id']}")
        print(f"  model={invoice['model']}  {invoice['llm_ms']} ms  "
              f"prompt_tokens={invoice['prompt_tokens']}  output_tokens={invoice['output_tokens']}")
        if invoice["status"] != "extracted":
            print(f"  FAILED: {invoice['error_code']}: {invoice['error_detail']}")
            total_wrong += len(FIELDS)
            continue
        print(f"  {'field':16} {'gold':28} {'extracted':28} ok")
        for name in FIELDS:
            ok = got[name] == gold[name]
            total_wrong += not ok
            print(f"  {name:16} {str(gold[name]):28} {str(got[name]):28} {'yes' if ok else 'NO'}")
        if invoice["invalid_fields"]:
            print(f"  invalid_fields: {invoice['invalid_fields']}")
    print(f"\nwrong fields: {total_wrong}")


if __name__ == "__main__":
    main()
