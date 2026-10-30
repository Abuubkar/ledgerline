---
status: accepted
date: 2026-10-30
---

# Uploaded PDFs go to S3-compatible storage, SeaweedFS locally

From slice 3a the API and the workers run as separate processes (and containers), so uploaded PDFs need
shared storage. The code talks to it only through the S3 API (boto3), and docker-compose runs SeaweedFS 4.51
(`chrislusf/seaweedfs:4.51`, Apache-2.0) as a single container that creates the `invoices` bucket on start.

## Considered options

The original plan named MinIO. Its community edition stopped publishing images in October 2025, went into
maintenance mode in December 2025, and its repository was archived (it now reads "no longer maintained").

| | AIStor Free | SeaweedFS | Garage | Shared Docker volume |
|---|---|---|---|---|
| License | Proprietary free license: no redistribution or modification; MinIO may change it at any time | Apache-2.0 | AGPL-3.0 | n/a |
| Cost | $0 (paid tiers are quote-only) | $0 | $0 | $0 |
| Setup for someone cloning the repo | Each person needs a license key from a MinIO SUBNET account; without one "All S3 operations are denied" | One container, bucket auto-created | Container plus a one-off CLI step for layout and keys | None |
| Limits | Single node only; no encryption at rest, replication or tiering | None relevant | None relevant | Ties API and worker to one machine |
| Activity (Oct 2026) | Commercial product | 4.51, 25 Oct 2026 | v2.5.0, 24 Oct 2026 | n/a |

- **AIStor Free** is real MinIO, but a public portfolio repo should run with `docker compose up` and no
  accounts or proprietary terms. MinIO's announcement says "no sign-up required" while its license docs say a
  SUBNET key is needed for S3 to work; the docs describe the server's behaviour, so they win.
- **Garage** is a good fit too, but its setup step adds friction for anyone trying the repo.
- **A shared volume** is the smallest change but isn't realistic for separate services.

Sources: AIStor Free agreement (min.io/legal/aistor-free-agreement), MinIO tier announcement (23 Dec 2025),
docs.min.io AIStor license page, github.com/minio/minio, github.com/seaweedfs/seaweedfs.

## Assumptions

- Only basic S3 calls are needed (put, get, head bucket); every option above supports them.
- Switching to AIStor Free, Garage, or AWS S3 is configuration: `S3_ENDPOINT_URL`, keys and bucket.
- Invoices store an `s3://bucket/key` URI rather than an endpoint URL, so the API (on the host) and workers
  (in Docker) can reach the same object through different endpoints.
