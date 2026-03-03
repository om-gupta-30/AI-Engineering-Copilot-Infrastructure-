# ─────────────────────────────────────────────────────────────────────────────
# AI Copilot Infra — production Dockerfile
#
# Layer cache strategy:
#   1. Install system deps          (changes rarely)
#   2. Install Poetry               (changes rarely)
#   3. Copy manifest + lock only    (invalidates on dep changes only)
#   4. Install Python deps          (expensive — kept in its own layer)
#   5. Copy source code             (invalidates on every code change)
#   6. Install package              (fast, just registers entry-points)
# ─────────────────────────────────────────────────────────────────────────────

FROM python:3.11-slim

# ── Environment ───────────────────────────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    POETRY_VERSION=1.8.3 \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PATH="/app/.venv/bin:$PATH"

# ── System dependencies ───────────────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────────────────
WORKDIR /app

# ── Install Poetry ────────────────────────────────────────────────────────────
RUN pip install "poetry==$POETRY_VERSION"

# ── Dependency layer (cache-optimised) ───────────────────────────────────────
# Copy manifests first. This layer only rebuilds when pyproject.toml or
# poetry.lock changes — not on every source code edit.
COPY pyproject.toml poetry.lock ./

RUN poetry install --without dev --no-root

# ── Application source ────────────────────────────────────────────────────────
COPY . .

# Install the package itself (registers ai_copilot_infra as importable)
RUN poetry install --without dev

# ── Port ──────────────────────────────────────────────────────────────────────
EXPOSE 8000

# ── Healthcheck ───────────────────────────────────────────────────────────────
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/health || exit 1

# ── Entrypoint ────────────────────────────────────────────────────────────────
CMD ["python", "infra/run.py"]
