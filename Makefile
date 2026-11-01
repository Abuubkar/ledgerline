OASDIFF := docker run --rm -v $(CURDIR):/specs:ro tufin/oasdiff:v1.35.0

.PHONY: codegen contract-check lint migrations-lint test test-int test-web web smoke chaos seed eval eval-test golden

# Regenerate everything derived from the contracts. Generated code is never edited by hand.
codegen:
	uv run python -c "from ledgerline_api.graphql import schema; print(schema.as_str())" > contracts/schema.graphql
	uv run openapi-python-client generate --path contracts/openapi.yaml --output-path packages/clients/python \
		--meta uv --overwrite --config contracts/client-config.yaml
	pnpm --dir apps/web codegen

# Fails if the running code would break a client generated from contracts/openapi.yaml.
contract-check:
	@mkdir -p build
	uv run python -c "import json; from ledgerline_api.main import app; print(json.dumps(app.openapi(), indent=2))" > build/openapi.emitted.json
	$(OASDIFF) breaking --fail-on ERR /specs/contracts/openapi.yaml /specs/build/openapi.emitted.json

# The same checks CI runs in its lint job (actionlint aside).
lint:
	uv run ruff check .
	uv run mypy
	pnpm --dir apps/web typecheck
	pnpm --dir apps/web lint

# Squawk on the SQL of migrations added since main (CI runs this on every PR).
migrations-lint:
	@uv run python scripts/migration_sql.py origin/main > build/new_migrations.sql
	@if [ -s build/new_migrations.sql ]; then uvx --from squawk-cli==2.70.0 squawk build/new_migrations.sql; else echo "No new migrations."; fi

test:
	uv run pytest -m "not integration"

test-int:
	uv run pytest -m integration

# Reviewer UI: Jest (offline, GraphQL mocked with MSW), and the dev server on :3000 (needs the API on :8000).
test-web:
	pnpm --dir apps/web test

web:
	pnpm --dir apps/web dev

smoke:
	uv run python scripts/smoke.py

# Slice 3a acceptance: 200 invoices + 3 corrupt PDFs, a stub model failing 15% of calls, one worker killed.
chaos:
	docker compose build worker
	uv run python scripts/chaos.py

# Realistic volume in the dev database plus the ERP mock's data (deterministic). PROFILE=large: ~1M invoice lines.
seed:
	uv run python scripts/seed.py --profile $(or $(PROFILE),small) --replace
	docker compose restart erp_mock

# Evals (evals/run.py): the dev split, replaying recorded model answers; LIVE=1 calls Ollama and records them.
# BASELINE=evals/baseline.json also fails on a drop of more than 1.5 points.
eval:
	uv run python evals/run.py $(if $(LIVE),--live,) $(if $(BASELINE),--baseline $(BASELINE),)

# The held-out test split: run only to check a finished change, never to tune against.
eval-test:
	uv run python evals/run.py --split test --out evals/test-split $(if $(LIVE),--live,)

# Re-render the 60 golden invoices (deterministic; only needed after changing scripts/make_invoice.py).
golden:
	uv run python scripts/make_invoice.py --golden
