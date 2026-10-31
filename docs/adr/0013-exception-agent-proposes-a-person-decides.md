---
status: accepted
date: 2026-11-01
---

# The exception agent proposes; a person decides

An invoice in `exception` needs someone to look at the PO, the receipts and the vendor's history and decide
what to do. The agent does the looking: `gemma4:12b` with Ollama tool calling (the model asks for a function
call, our code runs it and sends back the result) gathers evidence and proposes one action. A person approves
or rejects it. Nothing else is written.

## Decisions inside this

- **Model: gemma4:12b**, the extraction model (ADR 0001). It supports tool calling in Ollama, is already
  installed, and a second model would compete for 16 GB of memory. The original plan named
  qwen2.5:7b-instruct; slice 6's sweep can compare.
- **A plain loop, no agent framework**: chat with tools, run each call, append a `tool` message, repeat.
  About 100 lines, all inspectable (`agent.run_loop`).
- **Six tools**: `get_po`, `get_receipts`, `get_vendor_history`, `compute_variance` (reads),
  `draft_credit_memo_request`, `propose_hold` (writes that only create a `pending_actions` row).
- **Rules in code, not in the prompt.**
  - Each call's arguments are validated with Pydantic (`extra="forbid"`). An invalid call goes back to the
    model as the tool's error and still counts as a turn.
  - A credit memo request is refused until `get_receipts` and `compute_variance` have succeeded in this run
    (counted in `agent_runs.guard_fires`).
  - The credit amount isn't an argument at all: it's what `compute_variance` found over-billed on the named
    lines (billed minus PO price × quantity received). The model never does money arithmetic.
  - Budgets: 8 tool turns and 90 s per run (settings). Over either, the run proposes a hold with reason
    `agent_budget_exceeded`. The clock starts when the run gets the model slot, so time spent queueing
    behind extraction doesn't count. The run holds the slot until it finishes.
  - Every run ends with exactly one proposal. Answering without a tool also becomes a hold
    (`agent_no_proposal`), and only the first write call in a run counts.
- **Every step is stored as it happens** (`agent_runs`, `agent_steps`): each model response with its tool
  calls, and each tool call with its validated arguments and result or error. A run that dies midway still
  shows how far it got.
- **Optimistic concurrency for decisions.** `pending_actions.version` is the ETag. Approve and reject need
  `If-Match` (missing → 428). The decision is one conditional `UPDATE ... WHERE version = :seen AND status =
  'pending'`, so of two reviewers deciding at once exactly one wins and the other gets 412 with
  `current_version`. GraphQL mutations return a union (`DecisionSuccess | VersionConflict | NotFound`) instead
  of errors. Both call `service.decide_pending_action`.
- **At most one pending proposal per invoice** (partial unique index); a duplicate job delivery is skipped.
- **Approving only records the decision for now**: no invoice status change, nothing sent to a vendor or the
  ERP. That needs integrations we don't have; recording first keeps the approval flow testable on its own.
- **Runs are queued jobs** (`ledgerline.run_agent` on `invoices.agent`, through the outbox, with a dead-letter
  queue). Nothing starts them automatically yet: `scripts/agent_scenarios.py` queues them.

## Alternatives considered

- **Let the model state the credit amount and check it.** Rejected: a check that recomputes the amount makes
  the model's number redundant, and accepting it within a tolerance would let it drift.
- **LangChain / LangGraph.** Adds a dependency and hides the loop. The loop is short enough to own.
- **Auto-run the agent on every new exception.** The obvious end state, but each run takes ~40 s of model time
  that competes with extraction, and the 1,147 seeded exceptions would queue hours of work. Deferred until
  there's a priority between the two.

## Assumptions

- The 5 scenario runs (all five proposed the expected action) are a smoke test. Agent accuracy is measured on
  25 scenarios in slice 6.
- One reviewer identity is enough for now: there's no auth, so a decision records when and why, not who.
