import type { NextConfig } from "next";

// The browser talks only to this app; GraphQL and the REST API are proxied to the API server, so there's no
// cross-origin setup (CORS) and one origin for cookies when auth arrives.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  // A self-contained server in .next/standalone, which the image runs (apps/web/Dockerfile).
  output: "standalone",
  async rewrites() {
    return [
      { source: "/graphql", destination: `${API_URL}/graphql` },
      { source: "/v1/:path*", destination: `${API_URL}/v1/:path*` },
    ];
  },
};

export default config;
