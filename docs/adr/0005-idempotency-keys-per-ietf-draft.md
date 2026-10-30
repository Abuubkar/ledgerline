---
status: accepted
date: 2026-10-30
---

# Uploads are idempotent via Idempotency-Key, following the IETF draft

`POST /v1/invoices` requires an `Idempotency-Key` UUID and behaves as
draft-ietf-httpapi-idempotency-key-header-08 (22 Oct 2026) describes: missing key → 400, same key with a
different request → **422**, same key while the first request is still running → 409, and a finished request
is replayed with `Idempotent-Replayed: true`. The key is claimed with `INSERT ... ON CONFLICT DO NOTHING`
before any work starts, so of two concurrent requests exactly one proceeds.

Duplicate *content* is a separate rule (a request with a new key can still upload an invoice we already
have): a unique index on `content_sha256` that skips failed rows, checked before the model call and enforced
by the database when two uploads race.

## Considered options

- **409 for a reused key** (the original plan): the draft reserves 409 for "still processing", so clients
  following it would misread a 409.
- **No idempotency, rely on content duplicate detection**: catches the same file twice, but not a retried
  bulk request whose files partly succeeded, and gives the client no way to fetch the original response.
- **Hash the raw request body**: impossible, multipart boundaries are random; we hash filename, content type
  and content per file instead.

## Assumptions

- 24 hours is long enough for any client retry; keys aren't purged yet (no cleanup job until a worker exists).
- A request holding a key for more than 15 minutes has died (10 files × ~25 s is ~4 minutes). If extraction
  gets slower, raise `IDEMPOTENCY_LOCK_TIMEOUT_S`.
- Responses after a claim are stored and replayed, including 4xx results like a duplicate. Request-level
  validation errors (no key, too many files) happen before the claim and are not stored.
- Scanned PDFs have no text, so their fingerprint falls back to the file bytes; otherwise every scan would be
  a "duplicate" of every other.

## Update 2026-10-30 (slice 3a)

Uploads no longer wait for the model; a request now holds its key for well under a second (a 10-file upload
answered in 0.5 s). The 15-minute abandoned-claim timeout is far more than needed but harmless, so it stays.
Requests carry up to 50 files.
