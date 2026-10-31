# Problem types

Every error response is RFC 9457 `application/problem+json`. Its `type` links to a section here, and `code`
is stable: clients should branch on `code`, never on `title` or `detail`.

## invalid_request

400. The request didn't match the contract: a bad query parameter, a malformed Idempotency-Key, no files.
`detail` says which part.

## idempotency_key_missing

400. `POST /v1/invoices` needs an `Idempotency-Key` header holding a UUID you generate. Send the same key when
you retry the same upload.

## idempotency_key_reused

422. This key was already used with different files. Generate a new key for a new upload. (Follows
draft-ietf-httpapi-idempotency-key-header-08.)

## request_in_progress

409. A request with this key is still running. Uploads return as soon as the files are stored, so this only
lasts a moment. Retry with the same key; you'll get the stored result once it finishes.

## too_many_files

400. At most 50 files per request.

## unsupported_media_type

415. Only `application/pdf` is accepted. In a multi-file upload this appears as one file's result; the other
files are still processed.

## duplicate_invoice

409. An invoice with the same content is already stored. Also returned by a dead-letter replay when the same
content has been stored since the job failed. `duplicate_of` and `duplicate_of_url` point at it.
Content means the PDF's text with whitespace collapsed, or the raw bytes for PDFs without a text layer.
Failed extractions don't count, so you can re-upload after a model outage.

## invalid_cursor

400. The pagination cursor was edited, signed with another secret, or reused with different filters. Start
again from the first page.

## not_found

404. No invoice, dead letter or pending action with that id, or (for `/file`) no stored file for that invoice.

## queue_full

429. Too many extraction jobs are waiting. Nothing was stored, and the `Idempotency-Key` was released, so retry
the same request after the number of seconds in `Retry-After`.

## precondition_required

428. Approving or rejecting a pending action needs `If-Match` with the ETag from
`GET /v1/pending-actions/{id}`, so a reviewer can't decide on a version they never saw.

## version_conflict

412. The pending action changed since you read it (usually: someone else decided it first). `current_version`
says where it is now; reload it and decide again.

## action_already_decided

409. The pending action was already approved or rejected. `current_version` is its version now.

## Idempotency keys

Keys are kept for 24 hours. A key whose first request died without finishing is released after 15 minutes.
