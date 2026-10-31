// Shared test setup: the real urql client against MSW handlers, inside the providers the pages use.
import type { ReactNode } from "react";
import { Provider } from "urql";
import { graphql } from "msw/graphql";
import { setupServer } from "msw/node";
import { ListsProvider } from "@/components/Lists";
import { makeClient } from "@/lib/client";

export const GRAPHQL_URL = "http://localhost/graphql";
// MSW 3 scopes GraphQL handlers to an endpoint: gql.query(...), gql.mutation(...).
export const gql = graphql.link(GRAPHQL_URL);
export const server = setupServer();
beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

export function Providers({ children }: { children: ReactNode }) {
  // Node's fetch needs an absolute URL; the app itself uses "/graphql" through the Next.js proxy.
  const client = makeClient(GRAPHQL_URL);
  return <Provider value={client}><ListsProvider>{children}</ListsProvider></Provider>;
}
