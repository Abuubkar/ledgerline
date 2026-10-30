---
status: accepted
date: 2026-10-30
---

# The OpenAPI file is the contract; the app is checked against it, and GraphQL reuses the REST services

`contracts/openapi.yaml` is written by hand and is the source of truth. `make codegen` generates the typed
Python client from it (openapi-python-client 0.29.1); `make contract-check` dumps the FastAPI app's emitted
OpenAPI and runs `oasdiff breaking --fail-on ERR` (v1.35.0, Docker) between the two, failing if the code would
break a generated client. GraphQL (Strawberry) serves the UI's reads and calls the same `service.py`
functions as REST, so no rule is written twice.

## Considered options

- **Code-first (FastAPI's OpenAPI is the contract)**: less to maintain, but contract changes then happen as a
  side effect of refactors.
- **Exact equality between the file and the emitted spec**: FastAPI emits different titles and component
  shapes for the same contract, so this fails on cosmetics; a breaking-change check is the useful gate. It was
  verified to fail (exit 1) when a required response field is removed.

## Consequences and workarounds

- Nullable fields in the spec use `anyOf: [..., {type: 'null'}]`, the form Pydantic emits. The equivalent
  `type: [x, 'null']` made oasdiff report 49 false "type widened" breaks.
- FastAPI documents every response as `application/json` and adds a 422 validation response to each route;
  `main.openapi_with_problem_json` rewrites errors to `application/problem+json` and drops the 422s, because
  validation failures are 400 problems here.
- The `Idempotency-Key` header is declared with a UUID `pattern`, not `format: uuid`:
  openapi-python-client 0.29.1 passes a `uuid.UUID` object straight into the header and httpx raises
  `TypeError`. The server still rejects non-UUID keys.
- The Strawberry CLI needs an extra dependency set, so the GraphQL schema is exported with
  `schema.as_str()`; a test fails if `contracts/schema.graphql` drifts from the code.
- GraphQL `Int` is 32-bit (2^31 cents is $21.4M), so money amounts use a `BigInt` scalar, per Strawberry's
  documented pattern. JavaScript clients stay exact up to 2^53 minor units.

## Assumptions

- Only additive changes are made to the contract without a version bump; a breaking change needs a
  deliberate spec edit, which shows up in review.
- GraphQL stays read-mostly (mutations arrive in slice 5) and has no separate contract check beyond the schema
  drift test until CI adds graphql-inspector in slice 7.
