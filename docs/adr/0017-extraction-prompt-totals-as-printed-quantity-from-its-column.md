---
status: accepted
date: 2026-11-01
---

# Extraction prompt: totals only as printed, quantity from its own column

`extract-page/4` (and `repair-totals/4`, which shares the field rules) adds two rules:

- subtotal, tax and total: only the invoice's own figures, where they are printed. If they aren't printed, null.
  Never add up line amounts to fill them in.
- quantity: the number in the quantity column. A number inside a description (a pack size such as "5 reams") is
  part of the description, not the quantity.

## Why

The slice 6b sweep (`extract-page/3`) showed two reading errors that the existing "copy values exactly as printed,
never compute" rule didn't prevent:

- **qwen3.5:9b invented subtotals.** On 10 multi-page invoices it reported its own sum of a page's lines as that
  page's subtotal, where none was printed. The pages then disagreed with the real subtotal on the last page, and
  the merge correctly left the field invalid (ADR 0010). Subtotal accuracy: 72.5%.
- **gemma4:12b took pack sizes as quantities.** On 4 invoices the "5" in "A4 copy paper, 5 reams" became the
  quantity. It started once bare numbers were allowed (ADR 0016).

## Result (dev split; agent prompt unchanged)

| Model | Header avg / lowest field | Line F1 | Page p50 | Before (`extract-page/3`) |
|---|---|---|---|---|
| gemma4:12b | **100% / 100%** | **99.3%** | 34 s | 99.5% / 95.0%, line F1 96.4% |
| qwen3.5:9b-q4_K_M | 99.0% / 90.0% (tax ID) | 99.3% | 21 s | 96.2% / 72.5% (subtotal), 99.3% |
| qwen2.5:7b-instruct | 98.2% / 90.0% (subtotal) | **99.3%** | 14 s | 98.8% / 92.5%, 97.8% |

- **qwen3.5:** subtotal 72.5% → 100% and tax 97.5% → 100%. Its remaining miss is the Japanese invoice's
  "Registration No.: T…", which it doesn't treat as a tax ID (92.5% → 90%; it already missed most of these).
- **gemma4:** every header field and 137 of 139 lines right. The pack-size errors are gone; the two missed lines are
  under the rubber stamp (g27), as in every run so far.
- **qwen2.5 over-corrected.** Its lines improved (97.8% → 99.3%), but on the layout that labels the subtotal "Net
  GBP 3,572.00" it now answers null (subtotal 95% → 90%): it no longer counts "Net" as the invoice's subtotal.

The default model stays gemma4:12b, now with no failing header field. The baseline is its new run.

## Alternatives considered

- **Leave the prompt alone and pick the model that happens to read best.** Rejected: both errors break the rule we
  already state ("never compute"), so stating it precisely is cheap and helps every model.
- **Fix it in code:** drop a page's subtotal when it equals the sum of that page's lines. Rejected: a real one-page
  invoice prints exactly that, and code must never second-guess what was printed.
- **Name the labels in the prompt** ("Net", "Zwischensumme", "小計" mean subtotal). Not done yet: it would fix
  qwen2.5's "Net" misses but tunes the prompt to our six generated layouts. Worth trying only with real invoices.

## Assumptions

- 40 dev invoices on six generated layouts. Differences of one or two invoices (2.5–5 points on one field) are within
  run-to-run variation of a prompt change; the subtotal and pack-size fixes are well beyond that.
- The held-out test split hasn't been run on this prompt.
