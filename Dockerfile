# The Python services: one build, one target per service (api, worker, erp-mock), which differ only in their start
# command. The outbox relay and beat run the worker image with their own command (docker-compose.yml).
# Follows uv's Docker guide: dependencies in their own layer, then our code, installed non-editable so the runtime
# stage needs only the virtualenv.

FROM python:3.13-slim-trixie AS builder

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    UV_PYTHON_DOWNLOADS=0

WORKDIR /app

# Layer 1: third-party dependencies only; rebuilt when the lockfile changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=apps/api/pyproject.toml,target=apps/api/pyproject.toml \
    --mount=type=bind,source=apps/erp_mock/pyproject.toml,target=apps/erp_mock/pyproject.toml \
    --mount=type=bind,source=packages/clients/python/pyproject.toml,target=packages/clients/python/pyproject.toml \
    uv sync --frozen --no-install-workspace --no-editable

# Layer 2: our code, as installed packages.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-editable


FROM python:3.13-slim-trixie AS runtime

RUN useradd --create-home --uid 10001 ledgerline
WORKDIR /app
COPY --from=builder --chown=ledgerline /app/.venv /app/.venv
# Migrations ship with the image so a person can run `alembic upgrade head` as a one-off job; nothing applies them
# on start (docs/migrations.md).
COPY --chown=ledgerline alembic.ini /app/alembic.ini
COPY --chown=ledgerline apps/api/migrations /app/apps/api/migrations
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
USER ledgerline


FROM runtime AS api
EXPOSE 8000
CMD ["uvicorn", "ledgerline_api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS erp-mock
EXPOSE 8100
CMD ["uvicorn", "ledgerline_erp_mock.main:app", "--host", "0.0.0.0", "--port", "8100"]

# Last, so a plain `docker build .` (and docker compose) still gives the worker image.
FROM runtime AS worker
CMD ["celery", "-A", "ledgerline_api.worker", "worker", "--loglevel=INFO"]
