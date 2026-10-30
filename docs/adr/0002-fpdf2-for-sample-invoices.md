---
status: accepted
date: 2026-10-30
---

# fpdf2 renders the sample and golden-set invoice PDFs

`scripts/make_invoice.py` draws invoices in code with fpdf2 and writes the printed values as gold JSON next
to each PDF, so extraction always has real input whose correct answer is known by construction. fpdf2 is pure
Python with no system libraries, so it installs anywhere `uv sync` runs, including CI.

## Considered options

- **WeasyPrint + Jinja HTML templates** (the original plan): nicer layouts in HTML/CSS, but needs the `pango`
  system library (`brew install pango` on macOS, apt packages in CI) and an extra jinja2 dependency.
- **reportlab**: capable, but a heavier API than this needs.

## Assumptions

- Drawing six vendor layouts in code (slice 6) stays manageable. If layouts get complex, revisit.
- fpdf2's built-in fonts only cover Latin-1, so invoices print ISO currency codes (EUR, JPY) rather than
  symbols. Real invoices often use symbols; a TTF font can be added later to cover that case in the golden set.
- The generator is a dev tool only (`dev` dependency group); the running app never imports it.
