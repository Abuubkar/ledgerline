---
status: accepted
date: 2026-11-01
---

# The extraction schema accepts amounts as text or as bare numbers, read as Decimal

Every amount the model reads (subtotal, tax, total, and each line's quantity, unit price and amount) may now be a
JSON string, a JSON number, or null. A bare number is parsed with `json.loads(parse_float=Decimal)` and kept as the
exact digits written, so `3572.00` arrives as `"3572.00"` and no amount ever passes through a float (ADR 0003).
Prompt versions moved to `extract-page/3` and `repair-totals/3`.

## Why

Until now the schema allowed amounts only as `string | null`. Ollama enforces the `format` schema while the model
generates its answer, so a model that writes numbers unquoted has only one legal choice: `null`. gemma4:12b took the
other legal choice, a quote, and scored normally. The slice 6b model sweep showed that the Qwen models don't quote
them, and lost every number:

| Model (strings-only schema) | Header avg | Lowest field | Line F1 | Agent |
|---|---|---|---|---|
| gemma4:12b | 98.8% | 95.0% (vendor name) | 97.8% | 15/15 |
| qwen2.5:7b-instruct | 66.5% | 2.5% (totals) | 2.9% | 10/15 |

The prompt made it worse: it asks for amounts as "plain numbers … for example 1234.50", unquoted, while the schema
demanded strings. A model that follows the prompt (Qwen) starts writing a digit, and the grammar forbids that, so it
ends up at `null`. gemma4 followed the schema. The schema now allows what the prompt asks for.

A one-page probe confirmed the cause: the same qwen2.5 request with bare numbers allowed answered total 4286.4,
quantity 16 and unit price 223.25, all correct. A two-invoice trial of qwen3.5:9b-q4_K_M showed the same empty
numbers. Those were schema results, not model results, so comparing models on them would have been unfair. The
old numbers are kept in [evals/archive/2026-11-01-strings-only-schema/](../../evals/archive/2026-11-01-strings-only-schema/README.md).

## Result (dev split, same prompts otherwise)

| Model | Header avg / lowest field | Line F1 | Before (strings only) |
|---|---|---|---|
| gemma4:12b | 99.5% / 95.0% | 96.4% | 98.8% / 95.0%, line F1 97.8% |
| qwen2.5:7b-instruct | 98.8% / 92.5% | 97.8% | 66.5% / 2.5%, line F1 2.9% |
| qwen3.5:9b-q4_K_M | 96.2% / 72.5% | 99.3% | two-invoice trial, numbers empty |

gemma4 changed too, which we didn't expect. Its 6a answers quoted all 633 amounts, which looked like a preference;
it was the grammar. Given the choice it wrote all 558 as bare numbers. Subtotal, tax and total went to 100%, and on
4 invoices it took the "5" in "A4 copy paper, 5 reams" as the quantity. Lesson: what a model writes under a
constrained grammar says nothing about what it would write without the constraint. Details in docs/metrics.md
(slice 6b).

## Decisions inside this

- **`Amount` in `normalize.py`:** the Python type stays `str | None`, the JSON schema sent to the model says
  `string | number | null`, and pydantic's `coerce_numbers_to_str` turns an int into its digits. Code after parsing
  sees exactly what it saw before.
- **Parsing in one place:** `extraction.parse_answer` replaces `model_validate_json`, and any bad JSON is still an
  `invalid_model_output` page failure.
- **The model is still told to copy numbers as printed.** The schema now allows either form; the prompt wording is
  unchanged apart from the version bump, which marks that the request changed.

## Alternatives considered

- **Tell Qwen in the prompt to quote numbers.** Rejected: the grammar decides before the wording can help. A model
  whose first token is a digit can't then add a quote, and the probe showed the schema was the cause.
- **Numbers only (`number | null`).** Rejected: pydantic and most JSON parsers read numbers as floats by default,
  and a model that quotes would be forced not to. Accepting both costs nothing.
- **No schema (free JSON, validated afterwards).** Rejected: the schema is what keeps first-try validity at 100%.
  Without it, models wrap answers in prose or invent keys.
- **Parse floats and round to the currency's decimals.** Rejected by ADR 0003: code never rounds a printed amount.

## Consequences

- All recordings made with `extract-page/2` are stale. The sweep reran each model live, and `evals/baseline.json`
  is rewritten from gemma4's new run. The old recordings, results and baseline are archived, not deleted.
- Any model is now judged on reading, not on whether it happens to quote numbers.
