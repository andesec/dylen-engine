import os

# Mock environment to match what we see
os.environ["DGS_ALLOWED_ORIGINS"] = "https://app.dle.orb.local,"

# Import the config parsing logic
from app.config import _parse_origins

try:
  origins = _parse_origins(os.environ["DGS_ALLOWED_ORIGINS"])
  print(f"RAW: {os.environ['DGS_ALLOWED_ORIGINS']}")
  print(f"PARSED: {origins}")
  if len(origins) == 1 and origins[0] == "https://app.dle.orb.local":
    print("SUCCESS")
  else:
    print("FAILURE")
except Exception as e:
  print(f"ERROR: {e}")
