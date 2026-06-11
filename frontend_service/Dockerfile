# =============================================================================
# Stage 1 – base
# Shared OS + runtime config. Rebuilt only when the Node version changes.
# =============================================================================
FROM node:20-alpine AS base
ENV NODE_ENV=production
WORKDIR /app

# =============================================================================
# Stage 2 – deps
# Install production + dev dependencies.
# Rebuilt only when package.json or package-lock.json change.
# =============================================================================
FROM base AS deps
# libc6-compat is required for certain native Node addons on Alpine.
RUN apk add --no-cache libc6-compat

COPY package.json package-lock.json ./
RUN npm ci

# =============================================================================
# Stage 3 – builder
# Copy source and build. Rebuilt whenever any source file changes.
# node_modules come from the cached deps stage, not re-installed here.
# =============================================================================
FROM base AS builder
COPY --from=deps /app/node_modules ./node_modules
COPY . .

RUN npm run build

# =============================================================================
# Stage 4 – runner
# Minimal production image. Contains only the standalone server output,
# compiled static assets, and the public directory — no node_modules,
# no source files, no dev tooling.
# =============================================================================
FROM node:20-alpine AS runner
ENV NODE_ENV=production \
    PORT=3000 \
    HOSTNAME=0.0.0.0

WORKDIR /app

# Run as a non-root user.
RUN addgroup --system --gid 1001 nodejs \
 && adduser  --system --uid 1001 nextjs

# next build --standalone emits a self-contained server at .next/standalone.
# Static assets must be copied in separately; the standalone server does not
# bundle them.
COPY --from=builder --chown=nextjs:nodejs /app/public                   ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone          ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static             ./.next/static

USER nextjs

EXPOSE 3000

# server.js is the entrypoint emitted by the standalone build.
CMD ["node", "server.js"]
