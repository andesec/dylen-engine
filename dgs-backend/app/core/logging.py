"""Logging configuration and setup."""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path
from types import TracebackType

LOG_LINE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
LOG_FORMATTER = logging.Formatter(LOG_LINE_FORMAT, datefmt=LOG_DATE_FORMAT)
_LOG_FILE_PATH: Path | None = None
_LOGGING_INITIALIZED = False
logger = logging.getLogger("app.core.logging")


class TruncatedFormatter(logging.Formatter):
  """Formatter that truncates the stack trace to the last few lines."""

  # ruff: noqa: N802
  def formatException(
    self, ei: tuple[type[BaseException] | None, BaseException | None, TracebackType | None]
  ) -> str:
    import traceback

    lines = traceback.format_exception(*ei)
    # Keep header + last 5 lines of traceback
    if len(lines) > 6:
      return "".join(lines[:1] + ["    ...\n"] + lines[-5:])
    return "".join(lines)


def _build_handlers() -> tuple[logging.Handler, logging.Handler, Path]:
  """Create logging handlers anchored to the backend directory."""
  # Adjust path: app/core/logging.py -> app/core -> app -> dgs-backend -> logs?
  # Original: Path(__file__).resolve().parent.parent / "logs" from app/main.py
  # app/main.py is in dgs-backend/app. So parent is dgs-backend.
  # Here we are in dgs-backend/app/core. So parent.parent.parent is dgs-backend.

  log_dir = Path(__file__).resolve().parent.parent.parent / "logs"
  try:
    log_dir.mkdir(parents=True, exist_ok=True)
  except OSError as exc:
    raise RuntimeError(f"Failed to create log directory at {log_dir}: {exc}") from exc

  log_path = log_dir / f"dgs_app_{time.strftime('%Y%m%d_%H%M%S')}.log"
  try:
    # Touch early so the file exists even if handlers have not flushed yet.
    log_path.touch(exist_ok=True)
  except OSError as exc:
    raise RuntimeError(f"Failed to create log file at {log_path}: {exc}") from exc

  stream = logging.StreamHandler(sys.stdout)
  stream.setFormatter(TruncatedFormatter(LOG_LINE_FORMAT, datefmt="%H:%M:%S"))
  file_handler = logging.FileHandler(log_path, encoding="utf-8")
  file_handler.setFormatter(LOG_FORMATTER)
  return stream, file_handler, log_path


def setup_logging() -> Path:
  """Ensure all loggers use our handlers and propagate to root."""
  stream_handler, file_handler, log_path = _build_handlers()
  for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
    l = logging.getLogger(logger_name)
    l.handlers = [stream_handler, file_handler]
    l.propagate = False

  logging.basicConfig(level=logging.DEBUG, handlers=[stream_handler, file_handler], force=True)
  root = logging.getLogger()
  root.setLevel(logging.DEBUG)
  if not root.handlers:
    root.addHandler(stream_handler)
    root.addHandler(file_handler)

  if not log_path.exists():
    raise RuntimeError(f"Logging initialization failed; log file missing at {log_path}")
  return log_path


def _log_widget_registry() -> None:
  # app/core/logging.py -> app/core -> app -> schema
  rules_path = Path(__file__).parent.parent / "schema" / "widgets_prompt.md"
  try:
    from app.schema.widgets_loader import load_widget_registry

    registry = load_widget_registry(rules_path)
  except (FileNotFoundError, PermissionError, UnicodeDecodeError, ValueError) as exc:
    logger.warning("Failed to load widget registry from %s: %s", rules_path, exc)
    return

  widget_names = registry.available_types()
  logger.info(
    "Widget registry loaded from %s (%d types): %s",
    rules_path,
    len(widget_names),
    ", ".join(widget_names),
  )


def _initialize_logging() -> None:
  """Initialize logging and log startup messages."""
  global _LOG_FILE_PATH, _LOGGING_INITIALIZED
  if _LOGGING_INITIALIZED:
    return
  log_path = setup_logging()
  _LOG_FILE_PATH = log_path
  _LOGGING_INITIALIZED = True

  # Silence noisy libraries
  logging.getLogger("urllib3").setLevel(logging.ERROR)

  logger.info("Logging initialized. Writing to %s", _LOG_FILE_PATH)
  _log_widget_registry()
