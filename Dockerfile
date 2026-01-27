# ---------- Builder Stage ----------
FROM python:3.13-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

WORKDIR /app

# Copy only the lock files needed for deterministic installs.
COPY pyproject.toml uv.lock ./

# Install dependencies into a virtual environment.
RUN uv venv .venv && \
    . .venv/bin/activate && \
    uv sync --frozen --no-dev --no-install-project

# Copy the application source
COPY dgs-backend/ ./dgs-backend/

# ---------- Runtime Stage ----------
FROM python:3.13-slim AS production

WORKDIR /app

# Create a non-root user
RUN groupadd -r dgs && useradd -r -g dgs dgs && \
    ln -sf /usr/local/bin/python /usr/bin/python

# Copy the virtual environment from the builder.
COPY --from=builder --chown=dgs:dgs /app/.venv /app/.venv
COPY --from=builder --chown=dgs:dgs /app/dgs-backend /app/dgs-backend

# Set up environment variables
ENV PYTHONPATH="/app/dgs-backend:/app/.venv/lib/python3.13/site-packages"
ENV PATH="/app/.venv/bin:$PATH"

# Switch to non-root user
# Security Hardening: Remove shell and package managers (Distroless behavior)
RUN rm -rf /bin/sh /bin/bash /usr/bin/apt* /usr/lib/apt /var/lib/apt /usr/bin/dpkg* /var/lib/dpkg

USER dgs

# Expose the service port.
EXPOSE 8002

# Run the application.
CMD ["python", "dgs-backend/entrypoint.py"]

# ---------- Debug Stage ----------
FROM python:3.13-slim AS debug

WORKDIR /app

# Install git/build tools if needed for debug tools, though usually not required for pure python debug
# RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

# Copy uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

# Copy dependencies and source from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/dgs-backend /app/dgs-backend

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/dgs-backend:/app/.venv/lib/python3.13/site-packages"
ENV PYDEVD_DISABLE_FILE_VALIDATION=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install debugpy
RUN uv pip install debugpy --python .venv && \
    ln -sf /usr/local/bin/python /usr/bin/python

# We run as root in debug for convenience, or can switch to non-root if strongly desired.
# Staying root in debug is often easier for file permission issues with bind mounts.
# USER root (default)

EXPOSE 8002 5678

CMD ["python", "-Xfrozen_modules=off", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--log-to", "/tmp/debugpy", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
