"""The exception agent (ADR 0013): for an invoice in `exception`, the local model calls tools to gather
evidence and proposes one action, a credit memo request or a hold, which a person then approves or rejects.

A plain loop: chat with tools, run each tool call, send the result back as a "tool" message, repeat until the
model proposes or stops asking for tools. Rules enforced in code, not left to the prompt:
- every tool call's arguments are validated; an invalid call goes back to the model as an error;
- a credit memo request is refused unless get_receipts and compute_variance already ran in this run, and its
  amount comes from compute_variance, never from the model;
- at most `agent_max_turns` tool turns and `agent_wall_clock_s` seconds, after which the run proposes a hold;
- every run ends with exactly one proposal, which only creates a pending_actions row.
"""

import json
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Literal

from opentelemetry import trace
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ledgerline_api import matching, prompts
from ledgerline_api.db import AgentRun, AgentStep, GoodsReceipt, Invoice, PendingAction, PurchaseOrder
from ledgerline_api.errors import classify
from ledgerline_api.extraction import ExtractionError, call_model
from ledgerline_api.jobs import job_resources
from ledgerline_api.money import CURRENCY_EXPONENTS, format_minor
from ledgerline_api.normalize import po_number_key
from ledgerline_api.semaphore import llm_slot
from ledgerline_api.settings import settings

# --- tools: what the model may call, and with which arguments ------------------------------------------


class _Args(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetPo(_Args):
    po_number: str = Field(description="The purchase order number, as printed on the invoice")


class GetReceipts(_Args):
    po_number: str = Field(description="The purchase order number the goods were received against")


class GetVendorHistory(_Args):
    limit: int = Field(10, ge=1, le=25, description="How many recent invoices of this vendor to return")


class ComputeVariance(_Args):
    lines: list[str] = Field(default_factory=list,
                             description='Invoice lines such as "page 1 line 2"; empty for every line')


class DraftCreditMemoRequest(_Args):
    lines: list[str] = Field(min_length=1, description='The over-billed invoice lines, such as "page 1 line 2"')
    reason: str = Field(min_length=3, max_length=500, description="Why the vendor should credit these lines")


tracer = trace.get_tracer("ledgerline.agent")

HOLD_REASONS = ("missing_po", "duplicate", "tax_mismatch", "price_variance", "short_shipment", "other")


class ProposeHold(_Args):
    reason_code: Literal[HOLD_REASONS]  # type: ignore[valid-type]  # pydantic expands the tuple; one list of codes
    explanation: str = Field(min_length=3, max_length=500, description="One or two sentences for the reviewer")


TOOLS: dict[str, tuple[type[_Args], str]] = {
    "get_po": (GetPo, "The purchase order: vendor, currency and lines with ordered quantity and unit price."),
    "get_receipts": (GetReceipts, "Goods receipts for a purchase order and the quantity received per PO line."),
    "get_vendor_history": (GetVendorHistory, "The invoice vendor's most recent invoices, newest first."),
    "compute_variance": (ComputeVariance, "Per invoice line: billed vs due (PO price x quantity received)."),
    "draft_credit_memo_request": (DraftCreditMemoRequest, "Propose asking the vendor to credit over-billed lines."),
    "propose_hold": (ProposeHold, "Propose holding the invoice for a person, with a reason."),
}
WRITE_TOOLS = {"draft_credit_memo_request", "propose_hold"}
# draft_credit_memo_request is refused until these have run successfully in the same run.
CREDIT_MEMO_NEEDS = {"get_receipts", "compute_variance"}


def tool_schemas() -> list[dict]:
    return [
        {"type": "function", "function": {"name": name, "description": description,
                                          "parameters": model.model_json_schema()}}
        for name, (model, description) in TOOLS.items()
    ]


class ToolError(Exception):
    """Sent back to the model as the tool's result; the run goes on."""


class GuardRefused(ToolError):
    pass


def validate_call(name: str, arguments: object) -> _Args:
    if name not in TOOLS:
        raise ToolError(f"unknown tool {name!r}; the tools are {', '.join(TOOLS)}")
    try:
        return TOOLS[name][0].model_validate(arguments if isinstance(arguments, dict) else {})
    except ValidationError as exc:
        problems = "; ".join(f"{'.'.join(map(str, e['loc'])) or 'arguments'}: {e['msg']}" for e in exc.errors())
        raise ToolError(f"invalid arguments for {name}: {problems}") from None


# --- the arithmetic, in code ---------------------------------------------------------------------------


@dataclass
class VarianceLine:
    label: str
    description: str | None
    quantity: Decimal | None
    unit_price: Decimal | None
    amount_minor: int | None


def compute_variance(lines: list[VarianceLine], order: matching.Order | None, received: dict[int, Decimal] | None,
                     currency: str | None) -> dict:
    """What each invoice line bills against what is due for it: the PO's unit price times the quantity
    received (capped at the quantity billed). Over-billed = billed - due, never negative."""
    if order is None:
        raise ToolError("the invoice's purchase order isn't in the ERP data, so there's nothing to compare with")
    if currency != order.currency:
        raise ToolError(f"the invoice is in {currency} and the PO in {order.currency}; amounts can't be compared")
    exponent = CURRENCY_EXPONENTS[order.currency]
    unused, rows = list(order.lines), list[dict[str, Any]]()
    for line in lines:
        key = matching.description_key(line.description or "")
        po_line = next((c for c in unused if matching.description_key(c.description) == key), None)
        if po_line is None or line.quantity is None or line.amount_minor is None:
            rows.append({"line": line.label, "description": line.description, "billed_minor": line.amount_minor,
                         "due_minor": None, "overbilled_minor": None,
                         "note": "not on the PO" if po_line is None else "quantity or amount unreadable"})
            continue
        unused.remove(po_line)
        got = (received or {}).get(po_line.line_no, Decimal(0))
        due = int((min(line.quantity, got) * po_line.unit_price).scaleb(exponent).quantize(Decimal(1), ROUND_HALF_UP))
        rows.append({
            "line": line.label, "description": line.description,
            "billed_quantity": str(line.quantity), "received_quantity": str(got), "ordered_quantity": str(po_line.quantity),
            "billed_unit_price": str(line.unit_price), "po_unit_price": str(po_line.unit_price),
            "billed_minor": line.amount_minor, "due_minor": due, "overbilled_minor": max(0, line.amount_minor - due),
        })
    total = sum(row["overbilled_minor"] or 0 for row in rows)
    return {"currency": order.currency, "lines": rows, "total_overbilled_minor": total,
            "total_overbilled": format_minor(total, order.currency)}


def credit_memo_amount(variance: dict | None, lines: list[str]) -> int:
    """The credit to ask for: what compute_variance found over-billed on these lines."""
    if variance is None:
        raise GuardRefused("call compute_variance first; the credit amount is taken from it")
    by_line = {row["line"]: row for row in variance["lines"]}
    missing = [line for line in lines if line not in by_line]
    if missing:
        raise ToolError(f"compute_variance didn't cover {', '.join(missing)}; run it for those lines first")
    amount = sum(by_line[line]["overbilled_minor"] or 0 for line in lines)
    if amount <= 0:
        raise ToolError("nothing is over-billed on those lines; propose a hold instead if something is wrong")
    return amount


# --- the loop ------------------------------------------------------------------------------------------


@dataclass
class Proposal:
    action_type: Literal["credit_memo_request", "hold"]
    details: dict


@dataclass
class Step:
    kind: Literal["model", "tool"]
    content: str | None = None
    tool_name: str | None = None
    arguments: dict | None = None
    result: dict | None = None
    error: str | None = None
    llm_ms: int | None = None


@dataclass
class LoopResult:
    proposal: Proposal | None
    stop_reason: str  # proposed | no_proposal | agent_budget_exceeded
    tool_turns: int = 0
    guard_fires: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    llm_ms: int = 0
    steps: list[Step] = field(default_factory=list)


# chat(messages, timeout_s) -> (message with .content and .tool_calls, prompt_tokens, output_tokens, llm_ms)
Chat = Callable[[list, float], Awaitable[tuple]]
# execute(name, validated arguments) -> (result for the model, the proposal if it was a write tool)
Execute = Callable[[str, _Args], Awaitable[tuple[dict, Proposal | None]]]


async def run_loop(messages: list, chat: Chat, execute: Execute, on_step: Callable[[Step], Awaitable[None]],
                   max_turns: int, wall_clock_s: float, clock: Callable[[], float] = time.monotonic) -> LoopResult:
    """Talk to the model until it proposes, stops asking for tools, or runs out of turns or time."""
    deadline = clock() + wall_clock_s
    result = LoopResult(proposal=None, stop_reason="")
    succeeded: set[str] = set()

    async def record(step: Step) -> None:
        result.steps.append(step)
        await on_step(step)

    def budget_hold(why: str) -> LoopResult:
        result.stop_reason = "agent_budget_exceeded"
        result.proposal = Proposal("hold", {"reason_code": "agent_budget_exceeded", "explanation": why})
        return result

    while True:
        if result.tool_turns >= max_turns:
            return budget_hold(f"stopped after {result.tool_turns} tool turns without a proposal")
        remaining = deadline - clock()
        if remaining <= 0:
            return budget_hold(f"stopped after {wall_clock_s:.0f}s without a proposal")
        try:
            message, prompt_tokens, output_tokens, llm_ms = await chat(messages, remaining)
        except ExtractionError as exc:
            if exc.code == "model_timeout":  # the call ran into the run's deadline
                return budget_hold(f"stopped after {wall_clock_s:.0f}s without a proposal")
            raise
        result.prompt_tokens += prompt_tokens
        result.output_tokens += output_tokens
        result.llm_ms += llm_ms
        calls = message.tool_calls or []
        await record(Step("model", content=message.content or None, llm_ms=llm_ms,
                          arguments={"tool_calls": [{"name": c.function.name, "arguments": c.function.arguments}
                                                    for c in calls]} if calls else None))
        if not calls:
            result.stop_reason = "no_proposal"
            result.proposal = Proposal("hold", {
                "reason_code": "agent_no_proposal",
                "explanation": (message.content or "the agent ended without proposing an action")[:500],
            })
            return result
        messages.append(message)
        result.tool_turns += 1
        for call in calls:
            name, raw = call.function.name, call.function.arguments
            step = Step("tool", tool_name=name, arguments=raw if isinstance(raw, dict) else {"raw": str(raw)})
            proposal = None
            try:
                args = validate_call(name, raw)
                if name == "draft_credit_memo_request" and not CREDIT_MEMO_NEEDS <= succeeded:
                    missing = ", ".join(sorted(CREDIT_MEMO_NEEDS - succeeded))
                    raise GuardRefused(f"refused: call {missing} first, so the credit is based on what was received")
                step.result, proposal = await execute(name, args)
                succeeded.add(name)
            except ToolError as exc:
                if isinstance(exc, GuardRefused):
                    result.guard_fires += 1
                step.error = str(exc)
            await record(step)
            messages.append({"role": "tool", "tool_name": name,
                             "content": json.dumps(step.result if step.error is None else {"error": step.error})})
            if proposal is not None:
                result.proposal, result.stop_reason = proposal, "proposed"
                return result


# --- the job -------------------------------------------------------------------------------------------


@dataclass
class Evidence:
    """What the tools read for one invoice, loaded once per run."""

    invoice: dict
    vendor_id: uuid.UUID | None
    po_number: str | None
    currency: str | None
    lines: list[VarianceLine]
    variance: dict | None = None


def _invoice_summary(invoice: Invoice) -> dict:
    money = lambda minor: format_minor(minor, invoice.currency) if minor is not None and invoice.currency else None  # noqa: E731
    return {
        "invoice_number": invoice.invoice_number, "po_number": invoice.po_number,
        "vendor": invoice.vendor and {"name": invoice.vendor.name, "tax_id": invoice.vendor.tax_id},
        "invoice_date": invoice.invoice_date and invoice.invoice_date.isoformat(), "currency": invoice.currency,
        "subtotal": money(invoice.subtotal_minor), "tax": money(invoice.tax_minor), "total": money(invoice.total_minor),
        "lines": [{"line": f"page {line.page_no} line {line.line_no}", "description": line.description,
                   "quantity": line.quantity and str(line.quantity), "unit_price": line.unit_price and str(line.unit_price),
                   "amount": money(line.amount_minor)} for line in invoice.lines],
        "problems": {
            "invalid_fields": invoice.invalid_fields or {},
            "match": invoice.match.reasons if invoice.match else [],
        },
    }


async def _order_and_receipts(session, po_number: str | None):
    key = po_number_key(po_number)
    if key is None:
        return None, None, []
    order = (await session.execute(select(PurchaseOrder).where(PurchaseOrder.po_number_key == key))).scalar_one_or_none()
    receipts = (await session.execute(select(GoodsReceipt).where(GoodsReceipt.po_number_key == key)
                                      .order_by(GoodsReceipt.received_on))).scalars().all()
    received: dict[int, Decimal] | None = None
    if receipts:
        received = {}
        for receipt in receipts:
            for line in receipt.lines:
                received[line.po_line_no] = received.get(line.po_line_no, Decimal(0)) + line.quantity
    return order, received, receipts


def _executor(sessions, evidence: Evidence) -> Execute:
    async def execute(name: str, args: _Args) -> tuple[dict, Proposal | None]:
        # One span per tool call (GenAI execute_tool); arguments and results stay out of it (ADR 0020).
        with tracer.start_as_current_span(f"execute_tool {name}", attributes={
                "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name, "gen_ai.tool.type": "function"}) as span:
            try:
                return await _execute(name, args)
            except ToolError:
                span.set_status(trace.StatusCode.ERROR, "tool_error")
                raise

    async def _execute(name: str, args: _Args) -> tuple[dict, Proposal | None]:
        async with sessions() as session:
            if name == "get_po":
                assert isinstance(args, GetPo)  # validate_call built the tool's own argument model
                order, _, _ = await _order_and_receipts(session, args.po_number)
                if order is None:
                    return {"found": False, "po_number": args.po_number}, None
                return {
                    "found": True, "po_number": order.po_number, "status": order.status, "currency": order.currency,
                    "same_vendor_as_invoice": order.vendor_id == evidence.vendor_id,
                    "lines": [{"line_no": l.line_no, "description": l.description, "quantity": str(l.quantity),
                               "unit_price": str(l.unit_price)} for l in order.lines],
                }, None
            if name == "get_receipts":
                assert isinstance(args, GetReceipts)
                _, received, receipts = await _order_and_receipts(session, args.po_number)
                return {
                    "receipts": [{"received_on": r.received_on.isoformat(),
                                  "lines": [{"po_line_no": l.po_line_no, "quantity": str(l.quantity)} for l in r.lines]}
                                 for r in receipts],
                    "received_per_po_line": {str(n): str(q) for n, q in (received or {}).items()},
                }, None
            if name == "get_vendor_history":
                assert isinstance(args, GetVendorHistory)
                if evidence.vendor_id is None:
                    raise ToolError("the invoice has no recognized vendor")
                rows = (await session.execute(
                    select(Invoice).where(Invoice.vendor_id == evidence.vendor_id)
                    .order_by(Invoice.created_at.desc()).limit(args.limit)
                )).scalars().all()
                counts = dict((await session.execute(
                    select(Invoice.status, func.count()).where(Invoice.vendor_id == evidence.vendor_id).group_by(Invoice.status)
                )).all())
                return {"invoices_by_status": counts, "recent": [{
                    "invoice_number": r.invoice_number, "invoice_date": r.invoice_date and r.invoice_date.isoformat(),
                    "total": format_minor(r.total_minor, r.currency) if r.total_minor is not None and r.currency else None,
                    "status": r.status, "duplicate_of": (r.invalid_fields or {}).get("invoice_number"),
                } for r in rows]}, None
            if name == "compute_variance":
                assert isinstance(args, ComputeVariance)
                order, received, _ = await _order_and_receipts(session, evidence.po_number)
                wanted = set(args.lines)
                lines = [line for line in evidence.lines if not wanted or line.label in wanted]
                if wanted - {line.label for line in lines}:
                    raise ToolError(f"no such invoice line: {', '.join(sorted(wanted - {l.label for l in lines}))}")
                po = matching.Order(order.po_number, order.vendor_id, order.currency, [
                    matching.OrderLine(l.line_no, l.description, l.quantity, l.unit_price) for l in order.lines
                ]) if order else None
                result = compute_variance(lines, po, received, evidence.currency)
                # Later lookups by line merge into what was computed before.
                previous = {row["line"]: row for row in (evidence.variance or {"lines": []})["lines"]}
                previous.update({row["line"]: row for row in result["lines"]})
                evidence.variance = {**result, "lines": list(previous.values())}
                return result, None
        if name == "draft_credit_memo_request":
            assert isinstance(args, DraftCreditMemoRequest)
            amount = credit_memo_amount(evidence.variance, args.lines)
            assert evidence.variance is not None  # credit_memo_amount refuses without it
            details = {"amount_minor": amount, "currency": evidence.variance["currency"], "lines": args.lines,
                       "reason": args.reason}
            return {"proposed": "credit_memo_request", "amount": format_minor(amount, details["currency"])}, \
                Proposal("credit_memo_request", details)
        if name == "propose_hold":
            return {"proposed": "hold"}, Proposal("hold", args.model_dump())
        raise ToolError(f"unknown tool {name!r}")

    return execute


async def _chat(messages: list, timeout_s: float) -> tuple:
    response, prompt_tokens, output_tokens, llm_ms = await call_model(
        messages, tools=tool_schemas(), timeout_s=min(timeout_s, settings.llm_timeout_s),
        prompt_version=prompts.AGENT_VERSION,
    )
    return response.message, prompt_tokens, output_tokens, llm_ms


async def run(invoice_id: uuid.UUID, chat: Chat = _chat) -> str:
    """One agent run for an invoice in `exception`. Returns `proposed`, or `skipped` when the invoice isn't
    in exception or a proposal is already waiting for it. Raises TransientError / PermanentError."""
    async with job_resources() as (sessions, redis_client):
        async with sessions() as session:
            invoice = await session.get(Invoice, invoice_id)
            waiting = (await session.execute(select(PendingAction.id).where(
                PendingAction.invoice_id == invoice_id, PendingAction.status == "pending"))).first()
            if invoice is None or invoice.status != "exception" or waiting:
                return "skipped"
            evidence = Evidence(
                invoice=_invoice_summary(invoice), vendor_id=invoice.vendor_id, po_number=invoice.po_number,
                currency=invoice.currency,
                lines=[VarianceLine(f"page {l.page_no} line {l.line_no}", l.description, l.quantity, l.unit_price,
                                    l.amount_minor) for l in invoice.lines],
            )
            run_row = AgentRun(invoice_id=invoice_id, status="running", model=settings.llm_model,
                               prompt_version=prompts.AGENT_VERSION)
            session.add(run_row)
            await session.commit()
            run_id = run_row.id

        step_no = 0

        async def on_step(step: Step) -> None:
            # Each step is stored as it happens, so a run that dies midway still shows how far it got.
            nonlocal step_no
            step_no += 1
            async with sessions() as session:
                session.add(AgentStep(run_id=run_id, step_no=step_no, **asdict(step)))
                await session.commit()

        messages = [{"role": "system", "content": prompts.AGENT_SYSTEM},
                    {"role": "user", "content": prompts.agent_user(json.dumps(evidence.invoice, indent=1))}]
        try:
            # One model slot for the whole run: the wall clock measures the agent, not the queue for the model.
            async with llm_slot(redis_client):
                with tracer.start_as_current_span("invoke_agent exception-agent", attributes={
                        "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": "exception-agent",
                        "gen_ai.provider.name": "ollama", "gen_ai.request.model": settings.llm_model,
                        "gen_ai.prompt.version": prompts.AGENT_VERSION, "ledgerline.invoice_id": str(invoice_id)}) as span:
                    result = await run_loop(messages, chat, _executor(sessions, evidence), on_step,
                                            settings.agent_max_turns, settings.agent_wall_clock_s)
                    span.set_attributes({"ledgerline.agent.stop_reason": result.stop_reason,
                                         "ledgerline.agent.tool_turns": result.tool_turns})
        except Exception as exc:
            error = classify(exc)
            async with sessions() as session:
                run_row = await session.get(AgentRun, run_id)
                run_row.status, run_row.stop_reason, run_row.finished_at = "failed", error.code, func.now()
                await session.commit()
            raise error from exc

        async with sessions() as session:
            run_row = await session.get(AgentRun, run_id)
            run_row.status, run_row.stop_reason, run_row.finished_at = "proposed", result.stop_reason, func.now()
            run_row.tool_turns, run_row.guard_fires = result.tool_turns, result.guard_fires
            run_row.prompt_tokens, run_row.output_tokens, run_row.llm_ms = (
                result.prompt_tokens, result.output_tokens, result.llm_ms)
            assert result.proposal is not None  # every run_loop ends in exactly one proposal
            session.add(PendingAction(invoice_id=invoice_id, agent_run_id=run_id,
                                      action_type=result.proposal.action_type, details=result.proposal.details))
            try:
                await session.commit()
            except IntegrityError:
                # Another run proposed for this invoice first (a duplicate delivery): keep that one.
                await session.rollback()
                run_row = await session.get(AgentRun, run_id)
                run_row.status, run_row.stop_reason, run_row.finished_at = "failed", "superseded", func.now()
                await session.commit()
                return "skipped"
        return "proposed"

