# ==============================================================================
# Dockerfile — Single-Container Production Image for Cloud Run (Service & Job)
# Serves both the FastAPI REST API (/api/*) and the Beep Job Hub UI (/).
# Can also be executed as a Cloud Run Job with: python -m app.pipeline
# ==============================================================================
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    PORT=8080 \
    AUTO_SEED_ON_BOOT=true

WORKDIR /app

# Install system dependencies required by psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/backend/requirements.txt

# Copy backend and frontend assets preserving directory layout
COPY backend /app/backend
COPY frontend /app/frontend

WORKDIR /app/backend

EXPOSE 8080

# Default entrypoint runs the FastAPI web server (override command with `python -m app.pipeline` for Cloud Run Job)
CMD ["sh", "-c", "uvicorn app.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
