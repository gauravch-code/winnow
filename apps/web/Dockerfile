# Dashboard image for the self-hosted real app.
#
# NEXT_PUBLIC_WINNOW_MODE is a *build-time* var in Next (it's inlined
# into the client bundle), so it's a build ARG. Defaults to "real" —
# this image is the self-hosted dashboard. WINNOW_API_ORIGIN is a
# runtime var read by the server-side rewrite proxy.

# ---------- builder ----------
FROM node:20-slim AS builder
WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci

COPY apps/web/ ./

ARG NEXT_PUBLIC_WINNOW_MODE=real
ENV NEXT_PUBLIC_WINNOW_MODE=${NEXT_PUBLIC_WINNOW_MODE}
RUN npm run build

# ---------- runtime ----------
FROM node:20-slim AS runtime
WORKDIR /app

ENV NODE_ENV=production \
    PORT=3000

# Non-root.
RUN groupadd --system nodejs && useradd --system --gid nodejs --home /app nextjs

# Standalone output: minimal server + traced deps, plus static assets.
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public

USER nextjs
EXPOSE 3000

# server.js is emitted by Next's standalone build at the app root.
CMD ["node", "server.js"]
