# Backlog: improvements found but not done

Problems we know about and how we'd fix them, parked on purpose. Each entry says what's wrong, how big it is, the
suggested fix and its cost, and why it waits. Picking one up means following HOW_WE_BUILD.md like any change: a
prompt wording change bumps its version and reruns every model (`evals/sweep.py --live`), with the old results
archived first.

## Extraction

### The golden set has only one scanned invoice

- **What:** g13 (a page rendered as an image, tilted 2°, no text layer) is the only scan in the 60 golden invoices,
  and it's in the test split. The dev split, where prompts are tuned, never exercises reading from an image. On g13
  gemma4 paired two descriptions with the wrong numbers and misread the subtotal; code caught it (`exception`).
- **Fix:** have `scripts/make_invoice.py --golden` render more scans (several layouts, a few tilts, one low-contrast),
  spread across both splits, then rerun the models.
- **Cost:** new golden cases change the split for some existing ones only if they hash into the first 20 (ADR 0015);
  a full rerun of every model (~70 min plus rests), and the baseline moves.
- **Why it waits:** extraction from text layers is what the current numbers measure well; scans need their own pass.
- **Found:** slice 6d, 2026-11-01.

### Japan's registration number isn't read as the vendor's tax ID (qwen3.5 only)

- **What:** Japanese invoices print the seller's tax registration number as "Registration No.: T9876543210987"
  (T + 13 digits, required on qualified invoices since October 2023). qwen3.5:9b leaves `vendor_tax_id` empty on all
  4 such invoices in the dev split (tax ID 90%). gemma4 and qwen2.5 read it.
- **Why:** the prompt says "the seller's VAT or tax ID as printed", and "Registration No." doesn't say "tax".
- **Fix:** name the forms in the `vendor_tax_id` rule in `prompts._FIELD_RULES`, e.g. "the seller's VAT or tax ID as
  printed (a VAT number, USt-IdNr., or Japan's registration number, T followed by 13 digits)".
- **Cost:** a prompt version bump and a rerun of all three models (~70 min of model time plus rests).
- **Why it waits:** it only affects qwen3.5, which isn't the default. This is a real-world rule, not tuning to our
  layouts, so it's safe to add when qwen3.5 is considered seriously or with the next prompt change.
- **Found:** slice 6c (ADR 0017), 2026-11-01.

### "Net" isn't read as the subtotal (qwen2.5 only)

- **What:** one generated layout labels the subtotal "Net GBP 3,572.00". Since `extract-page/4`, qwen2.5:7b answers
  null there on 4 of 7 invoices (it read all 7 under `extract-page/3`). gemma4 and qwen3.5 read all 7. Tax and total
  stay right and the invoices still end `extracted`; only the subtotal is empty and the subtotal cross-check is
  skipped.
- **Why:** `extract-page/4` says "only the invoice's own figures, where printed… never add up line amounts". qwen2.5
  seems to distrust a figure labelled "Net" that equals the sum of the lines (our reading of the pattern).
- **Fix:** add common subtotal labels to the rule: "the subtotal may be labelled Net, Net amount, Zwischensumme, 小計
  (Shokei)…".
- **Cost:** as above, a version bump and a rerun of all three models.
- **Why it waits:** it tunes the prompt to the labels of our six generated layouts, and only affects qwen2.5, which
  isn't a candidate (agent 10/15). Worth trying against real invoices.
- **Found:** slice 6c (ADR 0017), 2026-11-01.

### A text stamp over line items scrambles the text layer (all models)

- **What:** on g27 a tilted "PAID 2026-10-31" stamp drawn as text sits over two line items. pdfplumber groups
  characters into lines by height, and the stamp's staircase of letters chains rows 2 and 3 into one "line", so their
  letters interleave (`U / Sa / S / f / B / e…`). Every model loses those 2 of 139 lines; the totals then don't add up
  and the invoice correctly goes to `exception`.
- **Fix (preferred):** detect scrambled page text (mostly one- or two-letter lines) and re-read that page with
  `extract_text(use_text_flow=True)` (draw order, which gives clean rows here) or as an image. Only broken pages
  change, so only their model calls rerun (minutes, not hours).
- **Alternatives:** always use draw order (breaks PDFs that draw columns separately); drop oversized or odd
  characters (guesswork).
- **Why it waits:** the user chose to leave it (2026-11-01). Real stamps are usually scanned images or annotations,
  which don't touch the text layer, so our generated stamp is harsher than most real PDFs.
- **Found:** slice 6b/6c, 2026-11-01.
