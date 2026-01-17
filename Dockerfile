FROM python:3.12-slim-bookworm AS base

# The installer requires curl (and certificates) to download the release archive
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates

# Download the latest installer
ADD https://astral.sh/uv/install.sh /uv-installer.sh

# Run the installer then remove it
RUN sh /uv-installer.sh && rm /uv-installer.sh

# Ensure the installed binary is on the `PATH`
ENV PATH="/root/.local/bin/:$PATH"

WORKDIR /app

# Copy the project configuration
COPY pyproject.toml uv.lock ./

# Install dependencies
RUN uv sync --frozen --no-install-project --no-dev

# Copy the application code
COPY . .

# Install the project itself
RUN uv sync --frozen --no-dev

# Place executables in the environment at the front of the path
ENV PATH="/app/.venv/bin:$PATH"

# Set the python path to include the backend directory
ENV PYTHONPATH="/app/dgs-backend"

# Production stage - minimal, secure, no debug tools
FROM base AS production

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Switch to non-root user
USER appuser

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]

# Debug stage - includes debugpy for development
FROM production AS debug

# Switch back to root to install debug tools
USER root

# Install debugpy for remote debugging
RUN uv pip install debugpy
ENV PYDEVD_DISABLE_FILE_VALIDATION=1

# Switch back to appuser
USER appuser

# Run the application with debugpy
CMD ["python", "-m", "debugpy", "--listen", "0.0.0.0:5678", "--wait-for-client", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
