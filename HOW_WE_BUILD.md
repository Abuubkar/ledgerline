# How we build this project

A professional AI project. The code is read and changed by people who did not write it, so it stays
**small, plain and consistent**: one working slice at a time, one way of doing each thing, and
abstractions only once the code has earned them.

## 1. Work in thin slices

Build in **vertical slices**: the smallest change that works end to end on real input (e.g. "load one
document type and answer one question from it"), not a layer at a time (all models, then all services…).

For every slice:

1. Say in one or two lines what the slice does and which files it touches.
2. Write only the code this slice needs. Later slices get their code when they arrive.
3. Run it on real input and show the output.

A slice is **done** when it runs, its output is shown, and anything not verified is named. Then stop and
report; the next slice starts from what this one taught.

## 2. Add things just in time

- **Packages:** propose a dependency when the first code that imports it is being written, with one line on
  why it's needed and what the standard library or an existing dependency lacks; once approved, add it in
  that same change. The dependency list holds only packages the code imports today.
- **Files and folders:** create them when code lands in them. A new folder gets a one-line reason in the
  change summary.
- **Infrastructure** (Docker services, queues, CI jobs, env vars, config keys): added by the first feature
  that uses it, in that feature's change.

## 3. One way per thing

The codebase has one current way of doing each job (calling the model, building prompts, querying the
store, handling config, logging). New code uses it.

- Before writing a helper or pattern, search for the existing one and reuse it.
- New code builds on the **current best version** of a piece, never on an older, simpler copy of it.
- Replacing a pattern with a better one means migrating its existing uses in the same change, or keeping
  the old pattern. Two live ways of doing one job is a defect.
- **Deliberate exception: GraphQL next to REST.** REST is the primary API (writes, integrations, generated
  clients). GraphQL serves the UI's reads and its few mutations, for hands-on experience. Both call the same
  service functions, so business logic is never written twice.

## 4. Keep it light

- **Plain first:** functions and plain data (dataclasses, dicts, Pydantic models) are the default.
  A class hierarchy, interface, registry, factory or plugin system arrives only with its **second real
  use**: two implementations that exist today, not one plus a possible future one.
- **Coarse functions:** one function per real job, readable top to bottom. Split when a piece is reused or
  tested on its own.
- **Plain words:** name things with the domain's words and the framework's own terms. Explain an AI term
  in one plain sentence the first time it appears in a doc or PR.
- **Framework before custom code:** use what the framework already ships. When the framework can't do
  something well, say so in the change summary.
- **Check current docs on the web, not from memory:** before using a library, service or API for the first
  time in a slice, web-search its official docs, release notes or changelog (not blog posts or generic
  tutorials). Confirm the current stable version, that the API isn't deprecated or legacy, and the
  recommended usage; pick the supported replacement if it is. List the URLs and versions you relied on in
  the slice report. When the docs and memory disagree, the docs win.
- **Comments say why:** a short comment for a non-obvious reason or a gotcha; the code says what.
- **AI pieces stay inspectable:** prompts live in one module, model names and parameters come from config,
  and every LLM decision that changes control flow (a route, a score, a plan) uses structured output and
  can be logged.

- **Record decisions as ADRs:** every real choice between alternatives (a model, a library, a data
  representation, a service) gets a short ADR in `docs/adr/NNNN-slug.md` in the same change: what was
  chosen, why, the alternatives considered, and the assumptions it rests on. When an assumption turns out
  wrong, supersede the ADR rather than editing history.

## 5. Tests: few, on business logic

Test the rules that decide outcomes: parsing, scoring and ranking rules, routing decisions,
data transforms, permission checks. Each test pins one behaviour a person would notice if it broke.

- Stub the LLM and external services at their boundary; unit tests run offline and fast.
- **Service tests** cover the infrastructure behaviour the product depends on: retries and dead letters,
  idempotency, pagination and resume, migrations up/down, queue acks and offset commits, optimistic
  concurrency. They run against real services in containers (testcontainers), are marked `integration`,
  and are kept to the cases that would lose or duplicate data if they broke.
- There is no coverage target. Coverage is reported, not gated.
- Framework wiring, prompt wording and config loading are covered by running the app, not by tests.
- Answer quality is measured by an **eval**: a small script over a fixed set of gold questions, run when
  retrieval, prompts or models change. It reports numbers; it is not a unit test.

## 6. Report briefly and honestly

After each slice: what changed (files), what ran and its output, what is not verified or not done.
Short headings, bullets, small tables. When a result is wrong or a test fails, show it.

## 7. Git: one short-lived branch per slice

Commits, merges and pushes don't need asking, as long as they follow these rules.

- `main` always runs. Each slice gets one branch, `slice/<NN>-<short-name>`, cut from an up-to-date `main`
  (`git switch main && git pull --ff-only` first, once a remote exists).
- **One open slice branch at a time per project.** That's what keeps branches from conflicting. A fix
  spotted outside the slice's files is noted for a later slice instead of being made on the side.
- Commit in small working steps with Conventional Commit messages (`feat(extract): …`, `fix(queue): …`,
  `test(match): …`, `chore(deps): …`).
- To finish a slice: `git fetch && git rebase origin/main`, rerun the checks, then merge.
  - Before a GitHub remote exists: `git switch main && git merge --ff-only slice/<NN>-…`.
  - With a remote: push the branch, open a PR with `gh pr create`, and merge with
    `gh pr merge --rebase --delete-branch` once CI (from slice 7 on) is green.
- Delete the slice branch after merging. Never force-push `main`; on a slice branch use only
  `--force-with-lease`.
- Generated files (clients, lockfiles, schema dumps) are regenerated after a rebase, never hand-merged.

## Ask first

- Adding a dependency or an external service
- Database schema changes and data migrations
- Anything that changes a public interface (API, CLI, file format) other code relies on
- Git actions outside section 7: rewriting `main`'s history, deleting branches you didn't create,
  changing repository settings or branch protection
