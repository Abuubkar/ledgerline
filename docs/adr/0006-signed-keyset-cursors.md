---
status: accepted
date: 2026-10-30
---

# Lists use keyset pagination with HMAC-signed cursors bound to the filters

`GET /v1/invoices` orders by `(created_at DESC, id DESC)` and continues from the last row's position with a
row-value comparison, backed by a matching index. The cursor is `base64url(payload).base64url(hmac)`, where
the payload holds that position and the filters it was issued for. A tampered cursor, one signed with another
secret, or one reused with different filters is rejected with 400 `invalid_cursor`. REST and GraphQL share
the same cursors.

## Considered options

- **Offset pagination**: simple, but slows down linearly with depth and skips or repeats rows when invoices
  arrive while a client is paging.
- **Unsigned cursors**: clients could craft positions and depend on the cursor format, freezing it.
- **Sort by `id` alone** (uuidv7 is time-ordered): would work today, but `created_at` is the business order
  and stays meaningful if ids ever come from elsewhere.

## Assumptions

- `CURSOR_SECRET` is set per deployment; rotating it invalidates outstanding cursors, which is acceptable
  (clients restart from page 1).
- Rows written in one transaction share `created_at`, so `id` must break ties; a service test pins this with
  five rows on one timestamp.
- Paging is forward-only for now; GraphQL reports `hasPreviousPage` only as "a cursor was passed".
