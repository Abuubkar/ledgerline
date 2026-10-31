"""Run the exception agent on one seeded invoice per scenario and print each trace and proposal.

Scenarios: price variance, short shipment, duplicate, missing PO, tax mismatch, picked from the dev database
after `make seed`, `scripts/sync_erp.py` and `scripts/match_pending.py`. The runs go through the queue like
production (the worker runs them with the real model), so the worker must be up.
Usage: uv run python scripts/agent_scenarios.py [--timeout 900]
"""

import argparse
import asyncio
import json
import time

from sqlalchemy import select, text

from ledgerline_api import service
from ledgerline_api.db import AgentRun, Invoice, PendingAction, SessionLocal

# (name, SQL condition picking an invoice in exception, the action a good reviewer would expect)
SCENARIOS = [
    ("price variance", "m.reasons @> '[{\"code\": \"price_variance\"}]' AND jsonb_array_length(m.reasons) = 1",
     "credit_memo_request"),
    ("short shipment", "m.reasons @> '[{\"code\": \"short_shipment\"}]' AND jsonb_array_length(m.reasons) = 1",
     "credit_memo_request"),
    ("duplicate", "i.invalid_fields ? 'invoice_number'", "hold: duplicate"),
    ("missing PO", "m.reasons @> '[{\"code\": \"po_not_found\"}]'", "hold: missing_po"),
    ("tax mismatch", "i.invalid_fields ? 'total' AND i.po_number IS NULL", "hold: tax_mismatch"),
]


def describe(action: PendingAction) -> str:
    details = action.details
    if action.action_type == "credit_memo_request":
        return f"credit_memo_request {details['amount_minor']} {details['currency']} minor units for {details['lines']}"
    return f"hold: {details['reason_code']}"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()

    picked = []
    async with SessionLocal() as session:
        for name, condition, expected in SCENARIOS:
            invoice_id = (await session.execute(text(f"""
                SELECT i.id FROM invoices i LEFT JOIN match_results m ON m.invoice_id = i.id
                WHERE i.status = 'exception' AND {condition}
                  AND NOT EXISTS (SELECT 1 FROM pending_actions p WHERE p.invoice_id = i.id)
                ORDER BY i.id LIMIT 1"""))).scalar_one()
            service.enqueue_agent(session, invoice_id)
            picked.append((name, invoice_id, expected))
        await session.commit()
    print(f"queued {len(picked)} agent runs; waiting for proposals (the model takes a while)...\n", flush=True)

    deadline = time.monotonic() + args.timeout
    while time.monotonic() < deadline:
        async with SessionLocal() as session:
            done = (await session.execute(select(AgentRun.invoice_id).where(
                AgentRun.invoice_id.in_([i for _, i, _ in picked]), AgentRun.status != "running"))).scalars().all()
        if len(set(done)) == len(picked):
            break
        await asyncio.sleep(3)

    async with SessionLocal() as session:
        for name, invoice_id, expected in picked:
            invoice = await session.get(Invoice, invoice_id)
            run = (await session.execute(select(AgentRun).where(AgentRun.invoice_id == invoice_id)
                                         .order_by(AgentRun.id.desc()))).scalars().first()
            action = (await session.execute(select(PendingAction).where(PendingAction.invoice_id == invoice_id))).scalars().first()
            print(f"=== {name}: invoice {invoice.invoice_number} ({invoice_id})")
            if run is None:
                print("    no run yet\n")
                continue
            for step in run.steps:
                if step.kind == "model":
                    calls = (step.arguments or {}).get("tool_calls", [])
                    said = f" says: {step.content[:120]!r}" if step.content else ""
                    print(f"  {step.step_no:>2}. model ({step.llm_ms / 1000:.1f}s){said}"
                          + (f" -> {', '.join(c['name'] for c in calls)}" if calls else ""))
                else:
                    shown = step.error and f"ERROR {step.error}" or json.dumps(step.result)[:160]
                    print(f"  {step.step_no:>2}. {step.tool_name}({json.dumps(step.arguments)[:80]}) -> {shown}")
            took = (run.finished_at - run.started_at).total_seconds() if run.finished_at else None
            print(f"  run: {run.status}, stop {run.stop_reason}, {run.tool_turns} tool turns, {run.guard_fires} guard "
                  f"fires, model {run.llm_ms / 1000:.1f}s" + (f", {took:.1f}s in all" if took else ""))
            print(f"  proposed: {describe(action) if action else '-'}")
            print(f"  expected: {expected}\n")


if __name__ == "__main__":
    asyncio.run(main())
