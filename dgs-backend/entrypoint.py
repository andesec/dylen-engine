import logging
import os
import subprocess
import sys

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("entrypoint")


def main():
  # 1. Run migrations
  logger.info("Running database migrations...")
  try:
    # Change to dgs-backend directory for migration script
    os.chdir("/app/dgs-backend")
    subprocess.run([sys.executable, "scripts/smart_migrate.py"], check=True)
  except subprocess.CalledProcessError as e:
    logger.error(f"Migration failed with exit code {e.returncode}")
    sys.exit(e.returncode)
  except Exception as e:
    logger.error(f"Unexpected error during migration: {e}")
    sys.exit(1)

  # 2. Start the application
  logger.info("Starting application...")
  # Use os.execvp to replace the current process with uvicorn
  # This ensures signals (SIGTERM, etc.) are handled correctly by uvicorn
  args = ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8002"]
  os.execvp("uvicorn", ["uvicorn"] + args[1:])


if __name__ == "__main__":
  main()
