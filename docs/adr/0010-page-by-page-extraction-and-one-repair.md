---
status: accepted
date: 2026-10-30
---

# Invoices are extracted page by page, checked by code, and repaired at most once

Each page is a separate model call: its text when it has a text layer, otherwise the page rendered to a 150 dpi
PNG and read by gemma4:12b's vision. Pages are merged in code: a header field takes the value the pages agree
on, and pages that disagree make the field invalid instead of picking one. Code then checks that the line
amounts plus tax equal the total (and the subtotal, when printed) within one minor unit. If not, the model
gets exactly one repair call naming the problem; if the repaired numbers add up they replace the page-by-page
result, otherwise the invoice goes to `exception` with the printed numbers kept and the total marked invalid.

## Decisions inside this

- **A page fails alone.** Bad model output, a prompt too long for the context, or an unparseable page fails
  only that page (`partially_extracted`). A model outage on any page retries the whole job, because it's
  transient. No extracted page at all dead-letters the job (`no_page_extracted`, or `empty_document` when
  every page is blank).
- **Blank pages are skipped, not failed.** The back of a scan is common and says nothing about the invoice.
  A page with no text layer is rendered; if it's essentially white, it's `blank` and no model call is made.
- **Repair only when every page was read.** With a page missing, a sum mismatch is expected, and a repair
  would cost ~30 s to change nothing.
- **Status precedence:** failed > partially_extracted > exception > extracted. A partial invoice with bad sums
  reports `partially_extracted`; the arithmetic problem is still in `invalid_fields`.
- **The model never does arithmetic, and code never "fixes" a number.** The repair prompt says to copy numbers
  as printed even if they don't add up; a misprinted invoice correctly ends in `exception`.
- **No new dependency for scans.** pdfplumber 0.11.10 already depends on pypdfium2 and Pillow, and
  `page.to_image()` renders through PDFium, so text and rendering share one PDF library. PDFium isn't
  thread-safe, so rendering runs under a lock.
- **Decimals as strings in the API.** Quantities and unit prices (which can be finer than a cent) are JSON
  strings; line amounts are money in minor units.

## The truncation guard was wrong, and how it's checked now

Slice 1 guarded against Ollama's silent prompt truncation with `prompt_eval_count >= num_ctx`. Measured on
2026-10-30 with gemma4:12b and `num_ctx` 8192: a ~9.7k-token prompt came back with **4,099** prompt tokens and
no error, so that guard would never have fired. Ollama's chat API has no option to error instead, and no
tokenizer endpoint. Now:

- **Before sending**, the prompt is budgeted at 2 characters per token plus ~600 tokens per image, leaving
  2,048 tokens for the answer. A page over budget fails with `prompt_too_long` without a model call. Measured:
  a real page prompt counts ~2.8 characters per token (the chat template and JSON schema add tokens the
  character count doesn't see); plain prose runs ~6.5. A first guess of 3 would have under-estimated.
- **After sending**, a text prompt reporting more than 10 characters per token is treated as truncated (the
  truncated case measured 15.5; intact page prompts ~2.8). `prompt_eval_count` includes cached prefix tokens
  (measured: 571 counted, 26 of them cached), so a reused system prompt doesn't make pages look truncated.

## Assumptions

- Pages are independent enough to read one at a time; header fields usually sit on the first page and totals
  on the last, which the merge handles.
- One repair call is enough to catch misreadings; it's a second look, not a loop.
- A missing tax line means zero tax (tax-exempt invoices print none).
- Image pages take ~30 s warm on the reference Mac (21 s of that is the image encoding), against ~24 s for a
  text page.
