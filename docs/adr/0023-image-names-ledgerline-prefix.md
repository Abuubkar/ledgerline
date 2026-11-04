---
status: accepted
date: 2026-11-04
---

# Image names get a ledgerline- prefix, published under both names for a month

The images move from `ghcr.io/abuubkar/ledgerline/<service>` to `ghcr.io/abuubkar/ledgerline-api`,
`ledgerline-worker`, `ledgerline-erp-mock` and `ledgerline-web` (the user's call). On the owner's package list the old
names read as bare `api`, `worker`, `web` next to other projects' packages; the prefix says which project each
belongs to.

## Decisions inside this

- **Both names for a month.** Each release pushes the same build to both names, so they carry the same digest,
  SBOM and provenance. It's scanned once and signed under each name (cosign stores signatures per repository).
  The old packages showed downloads. Most were our own release scans and checks, but GHCR doesn't say who pulled,
  and a hard rename would leave anyone tracking `ledgerline/api:main` on a frozen image without any error.
- **The old names stop on 2026-12-04** (docs/backlog.md has the exact change). Their packages stay in GHCR, so
  anything pinned to an old digest keeps working; deleting them is the owner's decision.
- **Flat names, not `ledgerline/ledgerline-api`:** the nested form would repeat the project's name.
- **New packages start private:** after the first release under the new names, each is made public in GHCR's
  package settings (no API for it), as the old ones were.

## Alternatives considered

- **Hard rename:** simplest, but it's the silent-staleness case above.
- **Keep the nested names:** no risk, and they're GitHub's default for repository-linked packages; the user wanted
  the project name in each package's own name.
