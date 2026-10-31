# One image for the worker, the outbox relay, beat and the ERP mock (and later the API). Follows uv's Docker guide:
# dependencies in their own layer, then the source.
FROM python:3.13-slim-trixie

COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1 \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Layer 1: third-party dependencies only; rebuilt when the lockfile changes.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    --mount=type=bind,source=apps/api/pyproject.toml,target=apps/api/pyproject.toml \
    --mount=type=bind,source=apps/erp_mock/pyproject.toml,target=apps/erp_mock/pyproject.toml \
    --mount=type=bind,source=packages/clients/python/pyproject.toml,target=packages/clients/python/pyproject.toml \
    uv sync --frozen --no-install-workspace

# Layer 2: our code.
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

RUN useradd --create-home --uid 10001 ledgerline && chown -R ledgerline /app
USER ledgerline

CMD ["celery", "-A", "ledgerline_api.worker", "worker", "--loglevel=INFO"]
