# =============================================================================
# Stage 1 – deps
# Install Python dependencies. Rebuilt only when requirements.txt changes.
# =============================================================================
FROM python:3.11-slim AS deps
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# =============================================================================
# Stage 2 – runner
# Copy sources into ./LLM_service/ so "python -m LLM_service.api" works from
# WORKDIR /app (the package sits at /app/LLM_service/__init__.py).
# =============================================================================
FROM deps AS runner
WORKDIR /app

COPY . ./LLM_service/

EXPOSE 8080

# API_HOST / API_PORT can be overridden at runtime; defaults match the serve() fn.
CMD ["python", "-m", "LLM_service.api"]
