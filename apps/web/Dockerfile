# The reviewer UI as a Next.js standalone server. Build from the repo root:
#   docker build -f apps/web/Dockerfile .
# The proxy target for /graphql and /v1 is fixed at build time (Next writes rewrites into the build), so API_URL is a
# build argument; the default fits a compose network with a service called `api`.

FROM node:24-slim AS build
RUN npm install --global pnpm@11.15.0
WORKDIR /web
COPY apps/web/package.json apps/web/pnpm-lock.yaml apps/web/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY apps/web/ ./
ARG API_URL=http://api:8000
ENV API_URL=$API_URL NEXT_TELEMETRY_DISABLED=1
RUN pnpm build


FROM node:24-slim AS runtime
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
WORKDIR /web
COPY --from=build --chown=node /web/.next/standalone ./
COPY --from=build --chown=node /web/.next/static ./.next/static
USER node
EXPOSE 3000
CMD ["node", "server.js"]
