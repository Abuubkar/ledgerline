import { cacheExchange, createClient, fetchExchange } from "urql";

// The document cache refetches any query that returned a PendingAction once a mutation returns one, so a case file
// shows the new version after a decision without hand-written cache updates.
export const makeClient = (url = "/graphql") => createClient({ url, exchanges: [cacheExchange, fetchExchange] });
