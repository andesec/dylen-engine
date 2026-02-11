"""Sync local dotenv values into GCP Secret Manager for stage deployments.

How/Why:
- Remove manual secret creation work during stage environment setup.
- Keep secret writes idempotent by skipping unchanged values.
- Enforce env-contract guardrails before values reach deployment systems.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
  # Ensure local `app` package is imported instead of similarly named site-packages.
  sys.path.insert(0, str(REPO_ROOT))

_ENV_KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _strip_inline_comment(*, value: str) -> str:
  """Remove comment suffixes from unquoted dotenv values."""
  match = re.search(r"\s#", value)
  if not match:
    return value.strip()

  return value[: match.start()].rstrip()


def _unescape_double_quoted(*, value: str) -> str:
  """Unescape minimal safe sequences in double-quoted dotenv values."""
  return value.replace("\\n", "\n").replace("\\r", "\r").replace("\\t", "\t").replace('\\"', '"').replace("\\\\", "\\")


def _parse_dotenv_line(*, raw: str, lineno: int, path: Path) -> tuple[str, str] | None:
  """Parse one dotenv line with strict syntax checks for safe automation."""
  line = raw.strip()
  if not line:
    return None

  if line.startswith("#"):
    return None

  if line.startswith("export "):
    line = line[len("export ") :].lstrip()

  if "=" not in line:
    raise RuntimeError(f"{path}:{lineno}: invalid line (expected KEY=VALUE).")

  key, value = line.split("=", 1)
  key = key.strip()
  if not _ENV_KEY_RE.fullmatch(key):
    raise RuntimeError(f"{path}:{lineno}: invalid key {key!r}.")

  value = value.lstrip()
  if not value:
    return key, ""

  if value.startswith("'"):
    trimmed = value.strip()
    if not trimmed.endswith("'") or len(trimmed) < 2:
      raise RuntimeError(f"{path}:{lineno}: unterminated single-quoted value.")

    return key, trimmed[1:-1]

  if value.startswith('"'):
    trimmed = value.strip()
    if not trimmed.endswith('"') or len(trimmed) < 2:
      raise RuntimeError(f"{path}:{lineno}: unterminated double-quoted value.")

    return key, _unescape_double_quoted(value=trimmed[1:-1])

  return key, _strip_inline_comment(value=value)


def _parse_dotenv_file(*, env_file: Path) -> dict[str, str]:
  """Read dotenv values without shell evaluation to avoid command injection."""
  values: dict[str, str] = {}
  text = env_file.read_text(encoding="utf-8")
  for lineno, raw in enumerate(text.splitlines(), start=1):
    parsed = _parse_dotenv_line(raw=raw, lineno=lineno, path=env_file)
    if not parsed:
      continue

    key, value = parsed
    values[key] = value

  return values


def _run_gcloud(*, args: list[str], input_text: str | None = None) -> subprocess.CompletedProcess[str]:
  """Run a gcloud command with captured output for deterministic script behavior."""
  return subprocess.run(["gcloud"] + args, input=input_text, text=True, capture_output=True, check=False)


def _secret_exists(*, project_id: str, secret_name: str) -> bool:
  """Check secret existence to avoid unnecessary create errors."""
  result = _run_gcloud(args=["secrets", "describe", secret_name, "--project", project_id, "--format=value(name)"])
  return result.returncode == 0


def _create_secret(*, project_id: str, secret_name: str) -> None:
  """Create a secret with automatic replication for managed multi-zone durability."""
  result = _run_gcloud(args=["secrets", "create", secret_name, "--project", project_id, "--replication-policy", "automatic"])
  if result.returncode != 0:
    raise RuntimeError(f"Failed to create secret {secret_name}: {result.stderr.strip()}")


def _read_latest_secret_value(*, project_id: str, secret_name: str) -> str | None:
  """Read latest secret value so unchanged writes can be skipped."""
  result = _run_gcloud(args=["secrets", "versions", "access", "latest", "--secret", secret_name, "--project", project_id])
  if result.returncode != 0:
    return None

  return result.stdout


def _add_secret_version(*, project_id: str, secret_name: str, value: str) -> None:
  """Write a new secret version using stdin to avoid temp files."""
  result = _run_gcloud(args=["secrets", "versions", "add", secret_name, "--project", project_id, "--data-file=-"], input_text=value)
  if result.returncode != 0:
    raise RuntimeError(f"Failed to add version for {secret_name}: {result.stderr.strip()}")


def _required_key_names(*, target: str) -> set[str]:
  """Collect required keys from the centralized runtime env registry."""
  from app.core.env_contract import REQUIRED_ENV_REGISTRY

  allowed_targets = {target, "both"}
  if target == "both":
    allowed_targets = {"service", "migrator", "both"}
  return {definition.name for definition in REQUIRED_ENV_REGISTRY if definition.required and definition.used_by in allowed_targets}


def _required_key_name_set_for_all_targets() -> set[str]:
  """Return required keys across service and migrator contracts."""
  from app.core.env_contract import REQUIRED_ENV_REGISTRY

  return {definition.name for definition in REQUIRED_ENV_REGISTRY if definition.required}


def _known_key_names(*, target: str) -> set[str]:
  """Collect known keys from the centralized runtime env registry."""
  from app.core.env_contract import REQUIRED_ENV_REGISTRY

  allowed_targets = {target, "both"}
  if target == "both":
    allowed_targets = {"service", "migrator", "both"}
  return {definition.name for definition in REQUIRED_ENV_REGISTRY if definition.used_by in allowed_targets}


def _normalize_secret_name(*, key: str, prefix: str) -> str:
  """Build secret names deterministically for script idempotency."""
  if not prefix:
    return key

  return f"{prefix}{key}"


def main() -> None:
  """Sync dotenv values into Secret Manager with safety checks and dry-run support."""
  parser = argparse.ArgumentParser(description="Sync dotenv values into GCP Secret Manager.")
  parser.add_argument("--project-id", required=True, help="Target GCP project ID.")
  parser.add_argument("--env-file", required=True, help="Path to local dotenv file (e.g. .env-stage).")
  parser.add_argument("--prefix", default="", help="Optional secret name prefix, e.g. STAGE_.")
  parser.add_argument("--default-dylen-env", choices=["development", "stage", "production", "test"], help="Set DYLEN_ENV to this value when it is missing from the env file.")
  parser.add_argument("--dry-run", action="store_true", help="Print planned actions without writing secrets.")
  parser.add_argument("--allow-unknown", action="store_true", help="Allow keys outside REQUIRED_ENV_REGISTRY.")
  parser.add_argument("--target", choices=["service", "migrator", "both"], default="service", help="Validate keys for service, migrator, or both contracts.")
  args = parser.parse_args()

  env_file = Path(args.env_file).resolve()
  if not env_file.is_file():
    raise RuntimeError(f"Env file not found: {env_file}")

  env_values = _parse_dotenv_file(env_file=env_file)
  if "DYLEN_ENV" not in env_values and args.default_dylen_env:
    # Provide an explicit fallback so stage/prod syncs can remain strict without editing local files each run.
    env_values["DYLEN_ENV"] = args.default_dylen_env
    print(f"INFO defaulted DYLEN_ENV={args.default_dylen_env}")

  known_keys = _known_key_names(target=args.target)
  required_keys = _required_key_names(target=args.target)
  unknown_keys = sorted([key for key in env_values if key not in known_keys])
  if unknown_keys and not args.allow_unknown:
    preview = ", ".join(unknown_keys[:10])
    raise RuntimeError(f"Unknown keys found in {env_file}: {preview}. Use --allow-unknown to bypass.")

  missing_required = sorted([key for key in required_keys if key not in env_values or env_values[key].strip() == ""])
  if missing_required:
    raise RuntimeError("Missing required keys in env file: " + ", ".join(missing_required))

  from app.core.env_contract import validate_env_values

  validation_errors = validate_env_values(target="service" if args.target == "both" else args.target, env_map=env_values)
  if args.target == "both":
    validation_errors = validation_errors + validate_env_values(target="migrator", env_map=env_values)
  if validation_errors:
    deduped_errors = sorted(set(validation_errors))
    raise RuntimeError("Contract validation failed for env file:\n- " + "\n- ".join(deduped_errors))

  created_count = 0
  updated_count = 0
  unchanged_count = 0
  failed_count = 0
  skipped_empty_count = 0
  required_key_set = _required_key_name_set_for_all_targets()

  for key, value in sorted(env_values.items(), key=lambda item: item[0]):
    if key in unknown_keys and not args.allow_unknown:
      continue

    if value == "" and key not in required_key_set:
      skipped_empty_count += 1
      print(f"SKIPPED_EMPTY secret {key}")
      continue

    secret_name = _normalize_secret_name(key=key, prefix=args.prefix)
    try:
      exists = _secret_exists(project_id=args.project_id, secret_name=secret_name)
      if not exists:
        if args.dry_run:
          print(f"DRY_RUN create secret {secret_name}")
        else:
          _create_secret(project_id=args.project_id, secret_name=secret_name)
        created_count += 1

      latest_value = _read_latest_secret_value(project_id=args.project_id, secret_name=secret_name)
      if latest_value is not None and latest_value == value:
        unchanged_count += 1
        print(f"UNCHANGED secret {secret_name}")
        continue

      if args.dry_run:
        print(f"DRY_RUN add version {secret_name}")
      else:
        _add_secret_version(project_id=args.project_id, secret_name=secret_name, value=value)
      updated_count += 1
      print(f"UPDATED secret {secret_name}")

    except Exception as exc:  # noqa: BLE001
      failed_count += 1
      print(f"FAILED secret {secret_name}: {exc}")

  print(f"SUMMARY created={created_count} updated={updated_count} unchanged={unchanged_count} skipped_empty={skipped_empty_count} failed={failed_count}")
  if failed_count > 0:
    raise RuntimeError("One or more secrets failed to sync.")


if __name__ == "__main__":
  main()
