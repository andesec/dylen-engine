import logging
import logging.handlers
import sys
import time
from pathlib import Path
from types import TracebackType

from app.config import Settings

LOG_LINE_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"
LOG_FORMATTER = logging.Formatter(LOG_LINE_FORMAT, datefmt=LOG_DATE_FORMAT)

# Track logging state
_LOG_FILE_PATH: Path | None = None
_LOGGING_INITIALIZED = False


class TruncatedFormatter(logging.Formatter):
  """Formatter that truncates the stack trace to the last few lines."""

  # ruff: noqa: N802
  def formatException(self, ei: tuple[type[BaseException] | None, BaseException | None, TracebackType | None]) -> str:
    import traceback

    lines = traceback.format_exception(*ei)
    # Keep header + last 5 lines of traceback
    if len(lines) > 6:
      return "".join(lines[:1] + ["    ...\n"] + lines[-5:])
    return "".join(lines)


def _build_handlers(settings: Settings) -> tuple[logging.Handler, logging.Handler, Path]:
  """Create logging handlers anchored to the backend directory."""
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

  file_handler = logging.handlers.RotatingFileHandler(log_path, encoding="utf-8", maxBytes=settings.log_max_bytes, backupCount=settings.log_backup_count)

  # Custom namer to format backup files as filename-x (e.g., app.log-1) instead of app.log.1
  def custom_namer(default_name: str) -> str:
    # default_name is something like /path/to/app.log.1
    # We want /path/to/app.log-1
    base_filename, ext, num = default_name.rpartition(".")
    if ext == "log" and num.isdigit():
      return f"{base_filename}.{ext}-{num}"
    # Fallback for unexpected formats, though RotatingFileHandler usually does .1, .2
    # If the rotation results in something like app.log.1, we want app.log-1
    # Let's handle the specific standard format: filename.1 -> filename-1
    parts = default_name.rsplit(".", 1)
    if len(parts) == 2 and parts[1].isdigit():
      return f"{parts[0]}-{parts[1]}"
    return default_name

  file_handler.namer = custom_namer
  file_handler.setFormatter(LOG_FORMATTER)
  return stream, file_handler, log_path


def setup_logging(settings: Settings) -> Path:
  """Ensure all loggers use our handlers and propagate to root."""
  stream_handler, file_handler, log_path = _build_handlers(settings)
  for logger_name in ("uvicorn", "uvicorn.error", "uvicorn.access", "fastapi"):
    log = logging.getLogger(logger_name)
    log.handlers = [stream_handler, file_handler]
    log.propagate = False

  logging.basicConfig(level=logging.DEBUG, handlers=[stream_handler, file_handler], force=True)
  root = logging.getLogger()
  root.setLevel(logging.DEBUG)
  if not root.handlers:
    root.addHandler(stream_handler)
    root.addHandler(file_handler)
  if not log_path.exists():
    raise RuntimeError(f"Logging initialization failed; log file missing at {log_path}")
  return log_path


def _log_widget_registry(logger: logging.Logger) -> None:
  rules_path = Path(__file__).parent.parent / "schema" / "widgets_prompt.md"
  try:
    from app.schema.widgets_loader import load_widget_registry

    registry = load_widget_registry(rules_path)
  except (FileNotFoundError, PermissionError, UnicodeDecodeError, ValueError) as exc:
    logger.warning("Failed to load widget registry from %s: %s", rules_path, exc)
    return

  widget_names = registry.available_types()
  logger.info("Widget registry loaded from %s (%d types): %s", rules_path, len(widget_names), ", ".join(widget_names))


def _initialize_logging(settings: Settings) -> None:
  """Initialize logging and log startup messages."""
  global _LOG_FILE_PATH, _LOGGING_INITIALIZED
  logger = logging.getLogger("app.core.logging")
  if _LOGGING_INITIALIZED:
    return
  log_path = setup_logging(settings)
  _LOG_FILE_PATH = log_path
  _LOGGING_INITIALIZED = True
  logger.info("Logging initialized. Writing to %s", _LOG_FILE_PATH)
  _log_widget_registry(logger)
