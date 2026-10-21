# syntax=docker/dockerfile:1.7
#
# TripWise frontend - production image (multi-stage, Next.js standalone server).
#
# NEXT_PUBLIC_* values are compiled into the browser bundle at BUILD time, so they are
# build arguments, and they are public by definition. Nothing secret may ever be passed
# here; the backend's secrets never reach this image.
#   NEXT_PUBLIC_API_MODE      live (default) = talk to the real backend; mock = MSW fixtures
#   NEXT_PUBLIC_API_BASE_URL  /api (default) = same-origin path routed by the reverse proxy
ARG NODE_IMAGE=node:22-bookworm-slim@sha256:3ed98443660ff48413b5af19ecefce3b9d50845a901a43420d47cc63a9fddbe9

FROM ${NODE_IMAGE} AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM ${NODE_IMAGE} AS build
WORKDIR /app
ARG NEXT_PUBLIC_API_MODE=live
ARG NEXT_PUBLIC_API_BASE_URL=/api
RUN case "${NEXT_PUBLIC_API_MODE}" in live|mock) ;; *) echo "NEXT_PUBLIC_API_MODE must be live or mock" >&2; exit 1;; esac
ENV NEXT_PUBLIC_API_MODE=${NEXT_PUBLIC_API_MODE} \
    NEXT_PUBLIC_API_BASE_URL=${NEXT_PUBLIC_API_BASE_URL} \
    NEXT_OUTPUT=standalone \
    NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# Note: next/font downloads and self-hosts the Google fonts at build time, so the BUILD
# (not the runtime container) needs outbound network access.
RUN npm run build

FROM ${NODE_IMAGE} AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0
WORKDIR /app
# Only the standalone server, its traced node_modules, static assets and public files.
COPY --from=build --chown=root:root /app/.next/standalone ./
COPY --from=build --chown=root:root /app/.next/static ./.next/static
COPY --from=build --chown=root:root /app/public ./public
USER node
EXPOSE 3000
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=6 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]
CMD ["node", "server.js"]
