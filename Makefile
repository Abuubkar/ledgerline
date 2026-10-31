OASDIFF := docker run --rm -v $(CURDIR):/specs:ro tufin/oasdiff:v1.35.0

.PHONY: codegen contract-check test test-int test-web web smoke chaos seed

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
