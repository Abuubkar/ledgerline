---
status: accepted
date: 2026-11-04
---

# Image names get a ledgerline- prefix

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
- **Visibility:** expected to start private, as the old packages did; in the first release (2026-11-04) the four new
  packages came out public, linked to the public repository, and `cosign verify` worked on them without logging in.
  Both names carried the same digests.

## Alternatives considered

- **Hard rename:** simplest, but it's the silent-staleness case above.
- **Keep the nested names:** no risk, and they're GitHub's default for repository-linked packages; the user wanted
  the project name in each package's own name.

## Update, 2026-11-04: the old names stopped the same day

The owner decided not to wait the month: the old names are no longer published (release.yml pushes and signs only
`ledgerline-<service>`), and the owner is deleting the old `ledgerline/<service>` packages in GHCR. Anyone still
pulling `ghcr.io/abuubkar/ledgerline/<service>` gets an error (GHCR answers 403 for a package that no longer
exists) and should switch to the new names.

