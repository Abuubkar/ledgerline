"""Print one invoice's trace from Jaeger as a span tree (slice 8a's Done-when check).

Finds the trace of the upload of `--invoice` (by the ledgerline.invoice_id attribute set on its jobs) or, without
it, the most recent upload trace, through Jaeger's v3 API, and prints each span with its service and duration.

  uv run python scripts/trace_tree.py [--invoice <uuid>] [--jaeger http://localhost:16686]
"""

import argparse
from datetime import UTC, datetime, timedelta

import httpx


def spans_of(trace: dict) -> list[dict]:
    """Flatten Jaeger's OTLP JSON into spans that carry their service name."""
    out = []
    for resource_spans in trace.get("resourceSpans", []):
        service = next((a["value"].get("stringValue") for a in resource_spans["resource"]["attributes"]
                        if a["key"] == "service.name"), "?")
        for scope in resource_spans.get("scopeSpans", []):
            for span in scope.get("spans", []):
                attrs = {a["key"]: next(iter(a["value"].values()), None) for a in span.get("attributes", [])}
                out.append({**span, "service": service, "attrs": attrs})
    return out


def find_traces(jaeger: str, service: str, attrs: dict[str, str] | None = None, hours: int = 2) -> list[list[dict]]:
    now = datetime.now(UTC)
    params = {"query.service_name": service, "query.start_time_min": (now - timedelta(hours=hours)).isoformat(),
              "query.start_time_max": now.isoformat(), "query.search_depth": 200}
    for key, value in (attrs or {}).items():
        params[f"query.attributes.{key}"] = value
    response = httpx.get(f"{jaeger}/api/v3/traces", params=params, timeout=30)
    response.raise_for_status()
    by_trace: dict[str, list[dict]] = {}
    for span in spans_of(response.json().get("result", {})):
        by_trace.setdefault(span["traceId"], []).append(span)
    return list(by_trace.values())


def print_tree(spans: list[dict]) -> None:
    children: dict[str, list[dict]] = {}
    ids = {s["spanId"] for s in spans}
    for span in spans:
        children.setdefault(span.get("parentSpanId") if span.get("parentSpanId") in ids else "", []).append(span)

    def show(span: dict, depth: int) -> None:
        ms = (int(span["endTimeUnixNano"]) - int(span["startTimeUnixNano"])) / 1e6
        extra = {k: v for k, v in span["attrs"].items() if k.startswith(("gen_ai.usage", "gen_ai.prompt", "ledgerline."))}
        print(f"{'  ' * depth}{span['service']:<8} {span['name']}  ({ms:,.0f} ms){'  ' + str(extra) if extra else ''}")
        for child in sorted(children.get(span["spanId"], []), key=lambda s: int(s["startTimeUnixNano"])):
            show(child, depth + 1)

    for root in sorted(children.get("", []), key=lambda s: int(s["startTimeUnixNano"])):
        show(root, 0)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--invoice")
    parser.add_argument("--jaeger", default="http://localhost:16686")
    args = parser.parse_args()
    traces = find_traces(args.jaeger, "worker", {"ledgerline.invoice_id": args.invoice} if args.invoice else None)
    uploads = [t for t in traces if any(s["service"] == "api" for s in t)]
    if not uploads:
        raise SystemExit("no trace with the upload request found")
    trace = max(uploads, key=lambda t: min(int(s["startTimeUnixNano"]) for s in t))
    print(f"trace {trace[0]['traceId']}: {len(trace)} spans across {sorted({s['service'] for s in trace})}\n")
    print_tree(trace)


if __name__ == "__main__":
    main()
