---
status: accepted
date: 2026-11-01
---

# CI: every pull request runs lint, contracts, tests, migration lint and the offline eval

`.github/workflows/ci.yml` runs on every pull request and every push to `main`. A PR merges only when all of it
passes (branch protection on `main`). Images, signing and releases are slice 7b.

| Job | What it checks |
|---|---|
| lint | ruff, mypy, tsc, eslint, actionlint |
| contracts | `make codegen` leaves no diff; code matches `contracts/openapi.yaml` (oasdiff); no breaking REST (oasdiff) or GraphQL (graphql-inspector) change against the base branch, unless the PR has the `breaking-change-approved` label |
| unit | `pytest -m "not integration"`, summary on the run page |
| integration | `pytest -m integration` against real Postgres in containers (testcontainers), summary on the run page |
| migrations | squawk on the SQL of the migrations the PR adds (rules in `.squawk.toml`) |
| web | Jest |
| eval-offline | `evals/run.py` replaying the recorded model answers, gated against the base branch's `baseline.json`; the metric table with deltas is posted as one sticky PR comment |

## Decisions inside this

- **Least privilege and pinned actions.** The workflow token can only read the repo; the eval job alone may write
  PR comments. Checkout doesn't keep credentials. Every third-party action is pinned to a full commit SHA with its
  version in a comment, at releases at least a week old. Tools that aren't actions run from pinned versions
  (`squawk-cli==2.70.0` via uvx, `@graphql-inspector/cli@7.0.2` via npx, `tufin/oasdiff:v1.35.0`, actionlint 1.7.12
  checked against its published SHA-256), so no action from an unknown publisher sees the repository.
- **Lint starts small, and green.** ruff with its defaults plus import order (I) and pyupgrade (UP); mypy in normal
  mode on `apps/api/src`, `apps/erp_mock/src` and `evals` (with the pydantic plugin); ESLint with Next's own
  `core-web-vitals` and `typescript` configs. Every finding was fixed in this slice rather than baselined. Exceptions,
  each with its reason in the config: `E741` (`l` is our name for an invoice line in comprehensions) and
  `react/no-unescaped-entities` (apostrophes in reviewer copy are plain text).
- **Squawk lints only new migrations.** `scripts/migration_sql.py` finds the migration files a branch adds and
  renders `alembic upgrade <start>:head --sql` for just those. Past migrations were reviewed when they landed
  (docs/migrations.md), and linting all of them on every PR repeats old decisions. Rules off, with reasons in
  `.squawk.toml`: `prefer-bigint-over-int`, `prefer-text-field`, `require-statement-timeout`. Everything else
  stays on, including non-concurrent index creation, table rewrites and a missing `lock_timeout`.
- **The eval in CI is the replay.** Runners have no GPU, so live evals stay on the reference Mac, and their
  recordings, `REPORT.md` and `baseline.json` are committed. CI replays them, so a code change that changes what's
  sent to the model fails with "no recorded answer" until someone reruns it live.
- **The sticky comment uses `gh`,** which is on the runner: `gh pr comment --edit-last --create-if-none` keeps one
  comment per PR, without a third-party action.

## Alternatives considered

- **Actions for every tool** (oasdiff-action, graphql-inspector's action, squawk-action). Rejected: each one is
  more third-party code with the repository checked out; the CLIs do the same with pinned versions.
- **Lint as report-only at first.** Rejected by the user: a check that doesn't fail is soon ignored.
- **Squawk on the whole migration chain.** Rejected: 48 warnings on reviewed, already-applied migrations, which
  would have to be excluded one by one.
- **A live eval on a self-hosted runner with a GPU.** Not free; out of scope.

## Assumptions

- GitHub-hosted `ubuntu-latest` runners have Docker (testcontainers and oasdiff need it).
- The repository stays public, so Actions minutes are free.
