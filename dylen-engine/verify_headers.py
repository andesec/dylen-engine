import os
import urllib.request

print("--- Testing Connectivity from within container ---")
try:
  url = "http://localhost:8002/v1/lessons/catalog"
  print(f"Requesting: {url}")

  req = urllib.request.Request(url)

  # Use the first allowed origin from environment variables, or fallback to a default
  allowed_origins = os.getenv("DYLEN_ALLOWED_ORIGINS", "https://app.dylen.orb.local")
  origin = allowed_origins.split(",")[0].strip()

  req.add_header("Origin", origin)

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
