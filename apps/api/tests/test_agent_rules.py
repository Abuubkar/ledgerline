from decimal import Decimal
from types import SimpleNamespace

import pytest

from ledgerline_api import agent
from ledgerline_api.agent import GuardRefused, Proposal, ToolError, VarianceLine, compute_variance, credit_memo_amount
from ledgerline_api.extraction import ExtractionError
from ledgerline_api.matching import Order, OrderLine

pytestmark = pytest.mark.anyio

ORDER = Order("4500000001", "v1", "EUR", [OrderLine(1, "Widget", Decimal(4), Decimal("10.00")),
                                         OrderLine(2, "Gadget", Decimal(2), Decimal("5.00"))])


def line(label="page 1 line 1", description="Widget", quantity="4", unit_price="10.00", amount=4000):
    return VarianceLine(label, description, Decimal(quantity), Decimal(unit_price), amount)


# --- compute_variance: the money the agent may ask back -------------------------------------------------


def test_price_above_the_po_is_over_billed_by_the_difference_times_quantity():
    result = compute_variance([line(unit_price="10.30", amount=4120)], ORDER, {1: Decimal(4)}, "EUR")
    assert result["lines"][0]["due_minor"] == 4000
    assert result["total_overbilled_minor"] == 120 and result["total_overbilled"] == "1.20"


def test_short_shipment_is_due_only_for_what_was_received():
    result = compute_variance([line()], ORDER, {1: Decimal(3)}, "EUR")
    assert (result["lines"][0]["due_minor"], result["total_overbilled_minor"]) == (3000, 1000)


def test_nothing_received_means_everything_billed_is_over_billed():
    assert compute_variance([line()], ORDER, None, "EUR")["total_overbilled_minor"] == 4000


def test_billing_less_than_due_is_never_negative():
    result = compute_variance([line(unit_price="9.00", amount=3600)], ORDER, {1: Decimal(4)}, "EUR")
    assert result["total_overbilled_minor"] == 0


def test_line_not_on_po_is_reported_not_priced():
    result = compute_variance([line(description="Gift basket")], ORDER, {1: Decimal(4)}, "EUR")
    assert result["lines"][0]["note"] == "not on the PO" and result["total_overbilled_minor"] == 0


def test_no_po_or_other_currency_is_a_tool_error():
    with pytest.raises(ToolError):
        compute_variance([line()], None, None, "EUR")
    with pytest.raises(ToolError):
        compute_variance([line()], ORDER, {1: Decimal(4)}, "USD")


def test_credit_memo_amount_comes_from_the_variance_for_the_named_lines():
    variance = compute_variance([line(unit_price="10.30", amount=4120),
                                 line("page 1 line 2", "Gadget", "2", "5.00", 1000)], ORDER, {1: Decimal(4), 2: Decimal(2)}, "EUR")
    assert credit_memo_amount(variance, ["page 1 line 1"]) == 120
    with pytest.raises(ToolError, match="nothing is over-billed"):
        credit_memo_amount(variance, ["page 1 line 2"])
    with pytest.raises(ToolError, match="didn't cover"):
        credit_memo_amount(variance, ["page 2 line 1"])
    with pytest.raises(GuardRefused):
        credit_memo_amount(None, ["page 1 line 1"])


# --- tool-call arguments ------------------------------------------------------------------------------


def test_tool_arguments_are_validated():
    assert agent.validate_call("get_po", {"po_number": "4500000001"}).po_number == "4500000001"
    with pytest.raises(ToolError, match="unknown tool"):
        agent.validate_call("pay_invoice", {})
    with pytest.raises(ToolError, match="po_number"):
        agent.validate_call("get_po", {})
    with pytest.raises(ToolError, match="reason_code"):
        agent.validate_call("propose_hold", {"reason_code": "because", "explanation": "looks odd"})
    with pytest.raises(ToolError, match="amount: Extra inputs"):  # no smuggling an amount past the code
        agent.validate_call("draft_credit_memo_request", {"lines": ["page 1 line 1"], "reason": "price", "amount": 9999})


# --- the loop: guard, budget, one proposal ------------------------------------------------------------


def call(name, **arguments):
    return SimpleNamespace(function=SimpleNamespace(name=name, arguments=arguments))


def scripted(*responses):
    """A model that answers with these responses in turn (each a list of tool calls, or text)."""
    replies = iter(responses)

    async def chat(messages, timeout_s):
        reply = next(replies)
        message = SimpleNamespace(content=reply if isinstance(reply, str) else None,
                                  tool_calls=None if isinstance(reply, str) else reply)
        return message, 100, 10, 5

    return chat


async def execute(name, args):
    if name == "draft_credit_memo_request":
        return {"proposed": name}, Proposal("credit_memo_request", {"lines": args.lines})
    if name == "propose_hold":
        return {"proposed": name}, Proposal("hold", args.model_dump())
    return {"ok": name}, None


async def no_record(step):
    pass


async def loop(chat, max_turns=8, wall_clock_s=90.0, clock=None):
    kwargs = {"clock": clock} if clock else {}
    return await agent.run_loop([], chat, execute, no_record, max_turns, wall_clock_s, **kwargs)


async def test_credit_memo_before_receipts_and_variance_is_refused_by_the_guard():
    result = await loop(scripted(
        [call("draft_credit_memo_request", lines=["page 1 line 1"], reason="price too high")],
        [call("get_receipts", po_number="4500000001")],
        [call("draft_credit_memo_request", lines=["page 1 line 1"], reason="price too high")],  # still no variance
        [call("compute_variance")],
        [call("draft_credit_memo_request", lines=["page 1 line 1"], reason="price too high")],
    ))
    assert result.guard_fires == 2
    refusals = [s.error for s in result.steps if s.error]
    assert "compute_variance, get_receipts" in refusals[0] and "compute_variance" in refusals[1]
    assert result.stop_reason == "proposed" and result.proposal.action_type == "credit_memo_request"
    assert result.tool_turns == 5


async def test_invalid_call_goes_back_to_the_model_and_counts_as_a_turn():
    messages = []
    chat = scripted([call("get_po")], [call("propose_hold", reason_code="missing_po", explanation="no PO found")])
    result = await agent.run_loop(messages, chat, execute, no_record, 8, 90)
    assert result.tool_turns == 2 and "invalid arguments for get_po" in result.steps[1].error
    assert '"error"' in messages[1]["content"]  # the error was sent to the model as the tool's result
    assert result.proposal == Proposal("hold", {"reason_code": "missing_po", "explanation": "no PO found"})


async def test_over_the_turn_budget_proposes_a_hold():
    result = await loop(scripted(*[[call("get_po", po_number="1")]] * 3), max_turns=3)
    assert result.stop_reason == "agent_budget_exceeded" and result.tool_turns == 3
    assert result.proposal.details["reason_code"] == "agent_budget_exceeded"


async def test_over_the_wall_clock_proposes_a_hold():
    now = [0.0]

    async def slow_chat(messages, timeout_s):
        now[0] += 50  # each model call takes 50 s
        return SimpleNamespace(content=None, tool_calls=[call("get_po", po_number="1")]), 1, 1, 50_000

    result = await loop(slow_chat, wall_clock_s=90, clock=lambda: now[0])
    assert result.stop_reason == "agent_budget_exceeded" and result.tool_turns == 2


async def test_a_model_call_cut_off_by_the_deadline_is_a_budget_hold_not_a_failure():
    async def timing_out(messages, timeout_s):
        raise ExtractionError("model_timeout", "no reply")

    assert (await loop(timing_out)).stop_reason == "agent_budget_exceeded"


async def test_answer_without_tools_still_ends_in_one_proposal():
    result = await loop(scripted("I think this needs a human."))
    assert result.stop_reason == "no_proposal"
    assert result.proposal == Proposal("hold", {"reason_code": "agent_no_proposal",
                                                "explanation": "I think this needs a human."})


async def test_only_the_first_write_counts():
    result = await loop(scripted([call("propose_hold", reason_code="duplicate", explanation="same as INV-1"),
                                  call("propose_hold", reason_code="other", explanation="second thoughts")]))
    assert result.proposal.details["reason_code"] == "duplicate"
    assert [s.tool_name for s in result.steps if s.kind == "tool"] == ["propose_hold"]
