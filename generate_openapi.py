import json
import os
import sys

# Add the project root to the python path
sys.path.append(os.getcwd())

from app.main import app


def generate_openapi():
  openapi_schema = app.openapi()

  # Save to file
  with open("openapi.json", "w") as f:
    json.dump(openapi_schema, f, indent=2)

  print("Successfully generated openapi.json")


if __name__ == "__main__":
  generate_openapi()
