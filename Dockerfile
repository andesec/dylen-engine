# ---------- Builder Stage ----------
FROM cgr.dev/chainguard/python@sha256:5c94ee31386cfbb226a41312a05f8f61b0d08635fc13812891be062c334d5428 AS builder

# Install uv by copying it from the official image
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
FROM mcr.microsoft.com/playwright:v1.50.1-jammy-python AS production

WORKDIR /app

# Copy the virtual environment from the builder.
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/dgs-backend /app/dgs-backend

# Set PYTHONPATH and PATH
ENV PYTHONPATH="/app/dgs-backend:/app/.venv/lib/python3.14/site-packages"
ENV PATH="/app/.venv/bin:$PATH"

# Install Playwright browsers (though the base image might have them, we ensure we use what crawl4ai needs or uses)
# The base image mcr.microsoft.com/playwright already has browsers.
# However, we need to ensure the python environment is set up.

# Expose the service port.
EXPOSE 8002

# Run the application.
CMD ["python", "dgs-backend/entrypoint.py"]

# ---------- Debug Stage ----------
FROM mcr.microsoft.com/playwright:v1.50.1-jammy-python AS debug

WORKDIR /app

# Copy everything from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/dgs-backend /app/dgs-backend
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/dgs-backend:/app/.venv/lib/python3.14/site-packages"
ENV PYDEVD_DISABLE_FILE_VALIDATION=1
ENV PYTHONDONTWRITEBYTECODE=1

# Install debugpy
RUN uv pip install debugpy --python .venv

EXPOSE 8002 5678

CMD ["python", "-Xfrozen_modules=off", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--log-to", "/tmp/debugpy", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
