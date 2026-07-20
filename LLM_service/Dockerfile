# =============================================================================
# Stage 1 – deps
# Install Python + Node dependencies. Rebuilt only when requirements.txt /
# video_renderer/package.json change.
#
# Build context is the REPO ROOT (see docker-compose.yml: `context: .`,
# `dockerfile: LLM_service/Dockerfile`) — not LLM_service/ — because this image
# also needs the sibling video_renderer/ Node project for the local Remotion CLI
# render subprocess (workflow/video/render.py shells out to `npx remotion render`
# there). A Docker build context can't reach outside its own directory, so the
# context has to be the directory that contains both.
# =============================================================================
FROM python:3.11-slim AS deps
WORKDIR /app

# Node 20 (NodeSource — Debian's default apt repo only has an old Node 18/lower).
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg ca-certificates \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

# Shared libraries Chromium needs to launch headless on a slim Debian image —
# Remotion's bundled/downloaded Chromium otherwise fails to start at all here.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libdrm2 libxkbcommon0 \
        libxcomposite1 libxdamage1 libxfixes3 libxrandr2 libgbm1 libasound2 \
        libpango-1.0-0 libpangocairo-1.0-0 fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

COPY LLM_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY video_renderer/package.json video_renderer/package-lock.json* ./video_renderer/
RUN cd video_renderer && npm install

# =============================================================================
# Stage 2 – runner
# Copy sources into ./LLM_service/ so "python -m LLM_service.api" works from
# WORKDIR /app (the package sits at /app/LLM_service/__init__.py), and
# ./video_renderer/ as its repo-root sibling — matching the local dev layout that
# core.config.Settings.resolved_video_renderer_dir defaults to (no VIDEO_RENDERER_DIR
# override needed in this image).
# =============================================================================
FROM deps AS runner
WORKDIR /app

COPY LLM_service/ ./LLM_service/
COPY video_renderer/ ./video_renderer/

EXPOSE 8080

# API_HOST / API_PORT can be overridden at runtime; defaults match the serve() fn.
CMD ["python", "-m", "LLM_service.api"]
