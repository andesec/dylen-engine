import os

# Mock environment to match what we see
os.environ["DYLEN_ALLOWED_ORIGINS"] = "https://dev.dylen.app,"

# Import the config parsing logic
from app.config import _parse_origins

try:
  origins = _parse_origins(os.environ["DYLEN_ALLOWED_ORIGINS"])
  print(f"RAW: {os.environ['DYLEN_ALLOWED_ORIGINS']}")
  print(f"PARSED: {origins}")
  if len(origins) == 1 and origins[0] == "https://dev.dylen.app":
    print("SUCCESS")
  else:
    print("FAILURE")
except Exception as e:
  print(f"ERROR: {e}")
