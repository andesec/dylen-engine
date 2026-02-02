from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _repo_root() -> Path:
  """Resolve the repository root so commands run from a stable working directory."""
  return Path(__file__).resolve().parents[1]


def _strip_inline_comment(*, value: str) -> str:
  """Remove a `# comment` suffix from an unquoted dotenv value."""
  # Only treat `#` as a comment delimiter when it is preceded by whitespace.
  match = re.search(r"\s#", value)
  if not match:
    return value.strip()

  return value[: match.start()].rstrip()


def _unescape_double_quoted(*, value: str) -> str:
  """Unescape minimal sequences supported in double-quoted dotenv values."""
  # Keep behavior minimal and predictable so env parsing stays safe and fast.
  return value.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")


def _parse_dotenv_line(*, raw: str, lineno: int, path: Path) -> tuple[str, str] | None:
  """Parse a single dotenv line, returning (key, value) or None when ignored/invalid."""
  line = raw.strip()
  if not line:
    return None

  if line.startswith("#"):
    return None

  if line.startswith("export "):
    line = line[len("export ") :].lstrip()

  if "=" not in line:
    raise RuntimeError(f"{path}:{lineno}: invalid line (expected KEY=VALUE): {raw.rstrip()}")

  key, value = line.split("=", 1)
  key = key.strip()
  if not _ENV_KEY_RE.fullmatch(key):
    raise RuntimeError(f"{path}:{lineno}: invalid key {key!r} (expected [A-Za-z_][A-Za-z0-9_]*): {raw.rstrip()}")

  value = value.lstrip()
  if not value:
    return key, ""

  if value.startswith("'"):
    # Single quotes are treated as literal values with no escape handling.
    trimmed = value.strip()
    if not trimmed.endswith("'") or len(trimmed) < 2:
      raise RuntimeError(f"{path}:{lineno}: unterminated single-quoted value: {raw.rstrip()}")

    return key, trimmed[1:-1]

  if value.startswith('"'):
    # Double quotes allow a small set of escapes for developer convenience.
    trimmed = value.strip()
    if not trimmed.endswith('"') or len(trimmed) < 2:
      raise RuntimeError(f"{path}:{lineno}: unterminated double-quoted value: {raw.rstrip()}")

    return key, _unescape_double_quoted(value=trimmed[1:-1])

  return key, _strip_inline_comment(value=value)


def _load_dotenv(*, dotenv_path: Path, override: bool) -> None:
  """Load a dotenv file into the current process environment."""
  if not dotenv_path.exists():
    return

  # Parse dotenv files without shell-sourcing so invalid lines produce actionable errors.
  text = dotenv_path.read_text(encoding="utf-8")
  for lineno, raw in enumerate(text.splitlines(), start=1):
    parsed = _parse_dotenv_line(raw=raw, lineno=lineno, path=dotenv_path)
    if not parsed:
      continue

    key, value = parsed
    if not override and key in os.environ:
      continue

    os.environ[key] = value


def main() -> None:
  """Run a command after loading env vars from a dotenv file (without sourcing)."""
  parser = argparse.ArgumentParser(description="Run a command with env vars loaded from a dotenv file.")
  parser.add_argument("--dotenv-file", default=".env", help="Dotenv file path (default: .env).")
  parser.add_argument("--override", action="store_true", help="Override existing env vars with values from the dotenv file.")
  parser.add_argument("command", nargs=argparse.REMAINDER, help="Command to run (prefix with --).")
  args = parser.parse_args()

  command = list(args.command)
  if command and command[0] == "--":
    command = command[1:]

  if not command:
    raise RuntimeError("No command provided. Usage: dotenv_run.py --dotenv-file .env -- <command> [args...]")

  # Ensure python invocations run under the same interpreter that executed this script.
  if command[0] in {"python", "python3"}:
    command[0] = sys.executable

  dotenv_path = (_repo_root() / args.dotenv_file).resolve() if not Path(args.dotenv_file).is_absolute() else Path(args.dotenv_file)
  try:
    _load_dotenv(dotenv_path=dotenv_path, override=bool(args.override))
  except RuntimeError as exc:
    # Provide a targeted hint because shell-sourcing errors are otherwise confusing.
    hint = "Hint: dotenv lines must be KEY=VALUE (e.g. DYLEN_ALLOWED_ORIGINS=https://app.dylen.orb.local)."
    raise RuntimeError(f"{exc}\n{hint}") from exc

  env = os.environ.copy()
  subprocess.run(command, check=True, cwd=_repo_root(), env=env)


if __name__ == "__main__":
  main()
