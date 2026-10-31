---
status: accepted
date: 2026-11-01
---

# The reviewer UI: Next.js App Router, urql, generated GraphQL types, plain CSS

A person decides what the agent proposes (ADR 0013), so the UI is the "case file" design picked from three
prototypes: one invoice at a time, the evidence next to the recommendation, keyboard-first (⌘K, J/K, A/R).
`apps/web` builds it.

## Decisions inside this

- **Next.js 16 (App Router) with client components.** Every screen is interactive and reads live data, so pages
  render in the browser; the server parts are routing and a proxy. Server-side data fetching would add a second
  data path for no reader benefit yet.
- **One origin.** Next.js rewrites `/graphql` and `/v1/*` to the API, so the browser never makes a cross-origin
  request: no CORS configuration, and one origin for cookies when auth arrives.
- **urql with its document cache.** It refetches any query that returned a `PendingAction` once a mutation returns
  one, so a decision updates the case file without hand-written cache code. Apollo's normalized cache solves
  problems we don't have.
- **Types generated from the contract.** `@graphql-codegen/client-preset` reads `contracts/schema.graphql` (itself
  generated from the API) and the documents in `src/lib/queries.ts`; `make codegen` regenerates both sides.
- **REST where GraphQL has no equivalent:** uploads (multipart) and dead letters (admin), in `src/lib/rest.ts`,
  typed by hand from `contracts/openapi.yaml`. Three calls don't justify a TypeScript client generator yet.
- **Plain CSS with tokens**, ported from the prototype; no CSS framework. Fonts (Instrument Sans, JetBrains Mono)
  are self-hosted by `next/font` at build time.
- **Icons copied as data** from Lucide (ISC licence) into `src/icons.ts`: 46 shapes, no icon package.
- **Plain language in one place.** `src/lib/present.ts` turns stored reasons ("billed 46, received 45") into
  sentences, explains the 3-way match as its checks, and labels jargon; acronyms (PO, ERP, VAT, AI) get a tooltip
  on hover and keyboard focus. Decision rules stay in the API: the UI's line tie-out is display only.
- **Money formatted from integer digits**, never by dividing a float. `formatMinor` and Python's `format_minor`
  are tested against the same fixtures (`packages/clients/fixtures/money.json`).
- **Tests: Jest via `next/jest`, React Testing Library, MSW** for GraphQL. MSW 3 ships only as ES modules, so Jest
  transforms it and its ES-module dependencies (`jest.config.js`); jsdom lacks `setImmediate`, which MSW needs
  (`jest.setup.ts`); MSW's `jest-fixed-jsdom` environment supplies the Fetch API.
- **The API gained what the screens need** (approved): `GET /v1/invoices/{id}/file` serves the stored PDF inline;
  GraphQL `Invoice` gained `purchaseOrder`, `goodsReceipts`, `pages` and the extraction details; `invoices` takes
  a `status` filter.

## Alternatives considered

- **Apollo Client:** heavier, normalized cache we don't need.
- **Tailwind or a component library:** faster to start, but the prototype's tokens and the "operate" guidance
  (standard controls, one committed palette) are a few hundred lines of CSS.
- **Vitest instead of Jest:** native ES modules would avoid the MSW workarounds; the slice plan named Jest, and
  `next/jest` is the officially documented path.

## Assumptions

- Desktop is the reviewer's device; narrow screens work but weren't designed for.
- No auth yet: the UI shows a demo reviewer, and decisions record when and why, not who.
- Invoices loaded by the seed script have no stored PDF; the file link says so instead of opening a tab.
