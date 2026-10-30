OASDIFF := docker run --rm -v $(CURDIR):/specs:ro tufin/oasdiff:v1.35.0

.PHONY: codegen contract-check test test-int smoke

# Regenerate everything derived from the contracts. Generated code is never edited by hand.
codegen:
	uv run python -c "from ledgerline_api.graphql import schema; print(schema.as_str())" > contracts/schema.graphql
	uv run openapi-python-client generate --path contracts/openapi.yaml --output-path packages/clients/python \
		--meta uv --overwrite --config contracts/client-config.yaml

# Fails if the running code would break a client generated from contracts/openapi.yaml.
contract-check:
	@mkdir -p build
	uv run python -c "import json; from ledgerline_api.main import app; print(json.dumps(app.openapi(), indent=2))" > build/openapi.emitted.json
	$(OASDIFF) breaking --fail-on ERR /specs/contracts/openapi.yaml /specs/build/openapi.emitted.json

test:
	uv run pytest -m "not integration"

test-int:
	uv run pytest -m integration

smoke:
	uv run python scripts/smoke.py
