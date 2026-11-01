---
status: accepted
date: 2026-11-01
---

# Releases: signed multi-arch images on GHCR, scanned before signing

Every push to `main` and every `v*` tag runs `.github/workflows/release.yml`. For each service (api, worker, erp-mock,
web) it builds a `linux/amd64` + `linux/arm64` image and pushes it to `ghcr.io/abuubkar/ledgerline/<service>`,
tagged `sha-<short>`, the branch name, and `X.Y.Z` / `X.Y` on a version tag. Each image carries an SBOM and a
provenance attestation. Trivy scans the pushed digest, and only a digest that passes is signed with cosign. A second
job renders every migration as SQL and keeps it as a run artifact; nothing applies migrations automatically.

## Decisions inside this

- **One Python Dockerfile, one target per service.** api, worker and erp-mock run the same virtualenv and differ only
  in their start command, so they share a builder stage and three short targets. The worker target is last, so
  `docker build .` and docker compose keep getting the worker. Our packages are installed non-editable, so the
  runtime stage holds the virtualenv, `alembic.ini` and the migrations, and no source tree. It runs as a non-root
  user. The api image is 114 MB.
- **The web image is Next's standalone server** (93 MB, runs as `node`). Next writes rewrites into the build, so the
  API address the UI proxies to is a build argument (`API_URL`, default `http://api:8000`).
- **Scan, then sign.** The image is pushed first (trivy needs a registry reference for a multi-arch image), then
  scanned by digest. A failing scan leaves it unsigned, and `cosign verify` refuses it. The scan fails on CRITICAL
  vulnerabilities that have a fix (`--ignore-unfixed`): an unfixable one in the base image can't be acted on and
  would block every release.
- **Keyless signing.** cosign signs with the workflow's GitHub OIDC identity through Sigstore (Fulcio certificate,
  Rekor log), so there's no signing key to store or leak. A signature proves the image came from this repository's
  release workflow on `main` or a tag:

  ```bash
  cosign verify ghcr.io/abuubkar/ledgerline/api:main \
    --certificate-identity-regexp '^https://github.com/Abuubkar/ledgerline/\.github/workflows/release\.yml@refs/(heads/main|tags/v.+)$' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
  ```
- **Trivy runs from its image, pinned by digest,** not through a third-party action. The other actions are pinned to
  commit SHAs, as in CI (ADR 0018).
- **arm64 builds under QEMU emulation** on the standard runner. It's slower than a native arm64 runner, but one job
  per service keeps the workflow simple. PRs build each image for amd64 without pushing (the `images` CI job, which
  shares the build cache), so a broken Dockerfile fails the PR rather than the release.

## Alternatives considered

- **Scan before pushing** (build, load locally, scan, then push). A multi-arch image can't be loaded into the local
  daemon, so it would mean scanning a separate single-arch build.
- **Signing with a stored key.** A key to rotate and protect; keyless ties the signature to the workflow identity.
- **Native arm64 runners and a manifest merge job.** Faster, but more workflow; worth it if release time becomes a
  problem.
- **Docker Hub.** GHCR uses the repository's own token and permissions, with no extra account.

## Assumptions

- The repository and its packages are public, so pulls and Actions minutes are free.
- Nothing deploys these images yet; slice 8 (observability) runs them.
