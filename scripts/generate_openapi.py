import json
import os
import sys

# Add app root to path to allow imports from 'app'
# This assumes the script is run from the repository root
sys.path.insert(0, os.getcwd())

from app.main import app  # noqa: E402, I001


def generate_openapi_spec():
  """Generates and writes the openapi.json spec file to the repo root."""
  repo_root = os.getcwd()
  openapi_spec = app.openapi()
  output_path = os.path.join(repo_root, "openapi.json")

  with open(output_path, "w", encoding="utf-8") as f:
    json.dump(openapi_spec, f, indent=2, sort_keys=True)
    f.write("\n")

  print(f"OpenAPI spec successfully written to {output_path}")


if __name__ == "__main__":
  generate_openapi_spec()
