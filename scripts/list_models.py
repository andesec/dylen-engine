import os
import sys

# Try to import google.genai
try:
  from google import genai
except ImportError:
  print("Error: google-genai module not found. Please ensure you are running in the correct environment.")
  sys.exit(1)

# Manual .env parsing
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
  try:
    if os.path.exists(".env"):
      with open(".env") as f:
        for line in f:
          line = line.strip()
          if line.startswith("GEMINI_API_KEY=") and not line.startswith("#"):
            api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
            break
  except Exception as e:
    print(f"Warning: Failed to read .env file: {e}")

if not api_key:
  print("Error: GEMINI_API_KEY not found in environment or .env file.")
  sys.exit(1)

try:
  client = genai.Client(api_key=api_key)
  print("Listing available models...")
  # The SDK might return an iterator or list
  models = list(client.models.list())

  found_any = False
  for m in models:
    # Check if it supports generateContent
    methods = m.supported_generation_methods or []
    if "generateContent" in methods:
      print(f"Model: {m.name}")
      print(f"  Display Name: {m.display_name}")
      print("-" * 20)
      found_any = True

  if not found_any:
    print("No models found that support generateContent.")
    print("All models found:", [m.name for m in models])

except Exception as e:
  print(f"Error listing models: {e}")
