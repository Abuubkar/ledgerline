---
status: accepted
date: 2026-11-04
---

# The release compose file runs everything: migrations, the app and observability

`docker compose -f docker-compose.yml -f docker-compose.release.yml up -d --wait` is the whole quick start. A
one-shot `migrate` service (the api image running `alembic upgrade head`) runs first; api, worker, relay and beat
wait for it to exit successfully. The collector, Jaeger, Prometheus, Loki and Grafana start too, and every app
service sends telemetry to the collector.

Development doesn't change: `docker compose up` stays lean, observability stays behind `--profile observability`
and telemetry behind `TRACING=1` (slice 8's choice, ADR 0021).

## Why

Before this, trying the published images took three commands and two settings: a separate migration run, then
`up` with `--profile observability` and `TRACING=1` to see the dashboard. Someone trying the project wants to see
everything, once; someone developing on it wants a light stack they turn things on in.

## Decisions inside this

- **Profiles are cleared with `profiles: !reset []`** in the release file, rather than moving the observability
  services into it. Their definitions stay in one place (docker-compose.yml) and only the release overlay turns
  them on by default. `!reset` needs Docker Compose 2.24 or newer.
- **Migrations as a service with `service_completed_successfully`**, not an entrypoint in the api image. The
  migration runs once per `up`, not once per replica, and a failed migration stops the app from starting, with
  its log under `docker compose logs migrate`. `up --wait` accepts the exited one-shot (checked with Compose 5.1).
- **The tracing endpoint is set directly** in the release file instead of through `TRACING`, because the
  collector is always there.

## Alternatives considered

- **Observability always on, in development too.** Simpler, but it's the extra memory slice 8 chose not to spend
  by default.
- **Migrate in the api container's start command.** Every api replica would race to migrate, and the worker could
  start before the schema exists.

## Assumptions

- Docker Compose 2.24 or newer (for `!reset`). Docker Desktop has shipped it since early 2024.
