import logging
import os

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("entrypoint")


def main() -> None:
  """Launch the service while keeping migrations in the deploy pipeline."""
  # Start the application; migrations are executed in a dedicated deploy step.
  logger.info("Starting application (run alembic upgrade head in deploy pipeline)...")
  # Use os.execvp to replace the current process with uvicorn.
  # This ensures signals (SIGTERM, etc.) are handled correctly by uvicorn.
  args = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002", "--no-server-header"]
  os.execvp("uvicorn", ["uvicorn"] + args[1:])


if __name__ == "__main__":
  main()
