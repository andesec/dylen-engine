import urllib.request
import sys
import os

print("--- Testing Connectivity from within container ---")
try:
  url = "http://localhost:8002/v1/lessons/catalog"
  print(f"Requesting: {url}")

  req = urllib.request.Request(url)
  req.add_header("Origin", "https://app.dle.orb.local")
  # Add dev key if needed, assuming 'local-dev-secret-key' from env
  dev_key = os.environ.get("DGS_DEV_KEY", "local-dev-secret-key")
  req.add_header("x-dgs-dev-key", dev_key)

  with urllib.request.urlopen(req) as response:
    print(f"Status: {response.getcode()}")
    print("Headers:")
    for k, v in response.headers.items():
      print(f"{k}: {v}")

except urllib.error.HTTPError as e:
  print(f"HTTPError: {e.code} {e.reason}")
  print("Headers:")
  for k, v in e.headers.items():
    print(f"{k}: {v}")
except Exception as e:
  print(f"Error: {e}")
