# Ledgerline

Accounts-payable automation: invoice PDFs in, structured and matched invoices out, built in thin slices.

- **How we work:** [HOW_WE_BUILD.md](HOW_WE_BUILD.md). It wins over everything else, including slice prompts.
- **Where it's heading:** [docs/architecture.md](docs/architecture.md). A destination, not a to-do list.
- **Why things are the way they are:** [docs/adr/](docs/adr/). Add one for every real choice.

## Run it

```bash
docker compose up -d --wait          # Postgres 18 on localhost:5434
uv run alembic upgrade head
ollama pull gemma4:12b               # once; Ollama runs natively on the Mac, not in Docker
uv run uvicorn ledgerline_api.main:app --port 8000
uv run python scripts/make_invoice.py    # writes samples/*.pdf + gold *.json
uv run python scripts/check_samples.py   # uploads them and compares with gold
uv run pytest
```

## Rules that are easy to break

- Money is always integer minor units + ISO currency. Never floats, never rounding (ADR 0003).
- Model name and options come from settings; prompts live only in `prompts.py`, and any wording change bumps
  its version.
- Always pass `num_ctx` to Ollama: its default silently truncates long prompts.
