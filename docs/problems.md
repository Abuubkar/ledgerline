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

409. A request with this key is still running (extraction takes about 25 s per invoice). Wait and retry with
the same key; you'll get the stored result once it finishes.

## too_many_files

400. At most 10 files per request while extraction is synchronous.

## unsupported_media_type

415. Only `application/pdf` is accepted. In a multi-file upload this appears as one file's result; the other
files are still processed.

## duplicate_invoice

409. An invoice with the same content is already stored. `duplicate_of` and `duplicate_of_url` point at it.
Content means the PDF's text with whitespace collapsed, or the raw bytes for PDFs without a text layer.
Failed extractions don't count, so you can re-upload after a model outage.

## invalid_cursor

400. The pagination cursor was edited, signed with another secret, or reused with different filters. Start
again from the first page.

## not_found

404. No invoice with that id.

## Idempotency keys

Keys are kept for 24 hours. A key whose first request died without finishing is released after 15 minutes.
