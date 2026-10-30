---
status: accepted
date: 2026-10-30
---

# Runtime baseline: Python 3.13 via uv, official Postgres 18 image, uv workspace from day one

- **Python 3.13** (uv-managed, pinned in `.python-version`). SQLAlchemy 2.1 needs ≥ 3.11 and pydantic-settings
  ≥ 3.11. 3.14 is installed too, but 3.13 is the safer bet for compiled wheels (asyncpg) across all the
  packages coming in later slices. The original plan said 3.12.
- **Postgres 18.6, official `postgres` image.** 18 brings `uuidv7()` for time-ordered primary keys. The
  pgvector image was approved, but Ledgerline uses no vectors yet, so the plain image is the smaller choice;
  switch when a slice needs vectors. Postgres 18 images moved PGDATA, so the volume mounts
  `/var/lib/postgresql`, not `/var/lib/postgresql/data`.
- **uv workspace root with one member (`apps/api`).** One member is an abstraction ahead of its second use,
  but the target layout has `apps/worker` and `apps/erp_mock` arriving in slices 3–4, and moving the package
  later would churn every import path. The root holds only dev tooling and is not a package.

## Assumptions

- Developers run Docker locally for Postgres; port 5432 is free (it was on 2026-10-30).
- No Postgres-18-only feature besides `uuidv7()` is relied on yet.
