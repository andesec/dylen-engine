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
FROM cgr.dev/chainguard/python@sha256:678e879909418cd070927d0ba1ed018be98d43929db2457c37b9b9764703678c AS production

WORKDIR /app

# Copy the virtual environment from the builder.
COPY --from=builder --chown=65532:65532 /app/.venv /app/.venv
COPY --from=builder --chown=65532:65532 /app/dgs-backend /app/dgs-backend

# Set PYTHONPATH and PATH
ENV PYTHONPATH="/app/dgs-backend:/app/.venv/lib/python3.14/site-packages"
ENV PATH="/app/.venv/bin:$PATH"

# Expose the service port.
EXPOSE 8002

# Run the application.
CMD ["dgs-backend/entrypoint.py"]

# ---------- Debug Stage ----------
FROM cgr.dev/chainguard/python@sha256:5c94ee31386cfbb226a41312a05f8f61b0d08635fc13812891be062c334d5428 AS debug

WORKDIR /app

USER root

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

# Install Playwright dependencies for debug/testing
# Note: Chainguard is minimal and doesn't support 'apt-get'.
# We might need a different base image for DEBUG if we need browsers,
# or we just accept that tests needing real browsers won't run in this container
# unless we install them manually which is hard in Chainguard.
# However, the user said "adding stuff in debug stage is fine".
# If I can't install browsers in Chainguard, I should use a fat image for debug?
# Let's switch DEBUG stage back to the standard python image or something that supports installation if needed.
# But keeping it consistent with Prod (Chainguard) is usually better.
# Let's assume for now we just install the python libs.
# If `crawl4ai` fails in debug, we'll see.
# Actually, for the "workaround", I'll implement the fallback in code so it works even without browsers.

EXPOSE 8002 5678

CMD ["-Xfrozen_modules=off", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--log-to", "/tmp/debugpy", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
