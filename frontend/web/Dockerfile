# Web client + reverse proxy image (docs/operations/DEPLOYMENT.md). Build from the
# repository root (npm workspaces):
#   docker build -f frontend/web/Dockerfile -t fms-web .
FROM node:22.13-alpine AS build
WORKDIR /repo
# Locked dependencies first (cached layer).
COPY package.json package-lock.json ./
COPY packages/shared/package.json packages/shared/
COPY packages/sync-core/package.json packages/sync-core/
COPY frontend/web/package.json frontend/web/
RUN npm ci --no-audit --no-fund
COPY packages packages
COPY frontend/web frontend/web
RUN npm run build --workspace web

FROM caddy:2.10.0-alpine
RUN setcap -r /usr/bin/caddy
COPY deploy/Caddyfile /etc/caddy/Caddyfile
# A configuration error fails the build instead of the deployment.
# RUN caddy format --overwhrite
RUN FMS_HTTPS_PORT=80 FMS_API_UPSTREAM=localhost:8000 caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
COPY --from=build /repo/frontend/web/dist /srv
