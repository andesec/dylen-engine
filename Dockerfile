# ---------- Builder Stage ----------
FROM python:3.11-slim-bookworm AS builder

# Install only the minimal system packages required to build wheels.
# `build-essential` provides gcc, make, etc.; `curl` is needed for the uv installer.
RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential curl ca-certificates && \
    rm -rf /var/lib/apt/lists/*

# Install uv (fast Python package manager) and add it to PATH.
ADD https://astral.sh/uv/install.sh /tmp/uv-installer.sh
RUN sh /tmp/uv-installer.sh && rm /tmp/uv-installer.sh
ENV PATH="/root/.local/bin:${PATH}"

WORKDIR /app

# Copy only the lock files needed for deterministic installs.
COPY pyproject.toml uv.lock ./
COPY dgs-backend/ ./dgs-backend/

# Create a virtual environment and install dependencies (exclude dev deps for prod).
RUN uv venv .venv && \
    . .venv/bin/activate && \
    uv sync --frozen --no-dev

# ---------- Runtime Stage (Distroless) ----------
FROM gcr.io/distroless/python3-debian12 AS production

# Copy the virtual environment from the builder.
COPY --from=builder /app/.venv /app/.venv

# Copy only the application source needed at runtime.
COPY --from=builder /app/dgs-backend /app/dgs-backend

# Set PYTHONPATH to include the backend package and site-packages.
ENV PYTHONPATH="/app/dgs-backend:/app/.venv/lib/python3.11/site-packages"

# Add venv bin to PATH (though we use direct path in CMD for clarity).
ENV PATH="/app/.venv/bin:$PATH"

# Expose the service port.
EXPOSE 8002

# Run the application using the full path to the uvicorn binary.
# Using exec form (JSON array) because Distroless has no shell.
CMD ["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]

# ---------- Debug Stage (Debian-based) ----------
# We base debug off 'builder' (Debian-slim) so we have a shell and tools.
FROM builder AS debug

# Install debugpy into the existing venv.
RUN . .venv/bin/activate && uv pip install debugpy

# Create a non-root user (optional but good practice to match prod user ID if needed).
# Distroless uses 'nonroot' (65532). We'll stick to 'appuser' (1000) for local debug convenience or match it.
# For simplicity in debug, we'll run as root or create appuser. Let's create appuser.
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

USER appuser

# Set PYTHONPATH same as prod.
ENV PYTHONPATH="/app/dgs-backend"
ENV PATH="/app/.venv/bin:$PATH"
ENV PYDEVD_DISABLE_FILE_VALIDATION=1

# Expose service and debug ports.
EXPOSE 8002 5678

# Run the application with debugpy.
CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
