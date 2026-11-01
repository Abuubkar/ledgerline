---
status: accepted
date: 2026-11-01
---

# Evals: a generated golden set, gates, and recorded model answers

Whether a prompt or model change helps has to be answered with numbers, not by eyeballing a few invoices.
`evals/run.py` scores extraction and the exception agent on a fixed golden set and fails when a gate is missed.

## Decisions inside this

- **The golden set is generated, so its answers are right by construction.** `scripts/make_invoice.py --golden`
  renders 60 invoices from their own data (6 vendor layouts with different labels and number formats, EUR, USD,
  JPY and GBP, 1–4 pages, one rotated scan with no text, one rubber stamp over the lines, three misprinted totals);
  the gold JSON is that data. Hand-labelled real invoices would test more realistic layouts but carry labelling
  errors and can't be committed. 25 agent scenarios are YAML files: the database state to seed, the invoice, the
  correct action and the evidence tools the agent should use.
- **A fixed split by hash.** Cases sorted by a hash of their id; the first 20 invoices and 10 scenarios are the test
  split, run only with `make eval-test`, so tuning happens on dev data only.
- **Scoring rules** (`evals/metrics.py`, unit-tested on hand-computed examples):
  - **Header fields:** exact match after normalizing what doesn't change meaning.
  - **Line items:** paired with the Hungarian algorithm (scipy) on description similarity (rapidfuzz
    `token_sort_ratio`); a pair is right only if the descriptions are ≥ 85% similar and quantity, unit price and
    amount are equal; micro-averaged F1.
  - **Schema validity:** pages answered in the required JSON shape.
  - **Calibration:** the share wrong among fields the model was ≥ 90% sure of.
- **Record and replay at the network boundary.** A live run stores every Ollama answer keyed by a hash of the
  request; a replay serves them back, so our own prompt budgeting, parsing, repair and agent loop still run. A
  request with no recording (a prompt or code change) stops the replay with a message to rerun live. Timing comes
  from Ollama's own durations in the answers, so a replay reports exactly the live latency and tokens/sec.
  Recordings are committed, which lets CI (slice 7) run the eval without a model.
- **The agent is evaluated against a real Postgres** in a container, seeded per scenario with ids derived from the
  scenario id, so the tool results (and therefore the requests) are identical run to run.
- **Results cached per (model, prompt version, case)** in `evals/cache/` (not committed): an interrupted live run
  resumes, and a rerun is instant. `--fresh` ignores the cache after a code change that keeps the prompt versions.
- **Gates** as planned (header macro ≥ 95%, each field ≥ 93%, line F1 ≥ 88%, schema validity ≥ 98%, calibration
  error ≤ 3%, agent action accuracy ≥ 75%, p95 ≤ 45 s); a baseline file adds "no drop of more than 1.5 points".
  They're the original targets; the first baseline run proposes recalibrated ones, and the user decides.

## Alternatives considered

- **Mock the model in replay at our `call_model` function:** simpler, but skips the code between our function and
  Ollama's answer (truncation checks, budget errors), which is exactly what a refactor could break.
- **An LLM judge for descriptions:** fuzzy matching is deterministic, free, and good enough for copied text.
- **Hand-written Hungarian algorithm or difflib:** no dependency, but more code to own; scipy and rapidfuzz are the
  standard tools (dev-only dependencies).

## Assumptions

- Generated layouts stand in for real vendors. They test reading, multi-page merging and number formats, not the
  messiness of real scans; real invoices would need labelling (later, if needed).
- Model time per invoice is the sum of its calls (pages are read one after another), with model loading excluded.
- The agent's correct action is unambiguous in each scenario; borderline cases (goods not yet received: hold, not
  credit) are documented in the scenario's description.
