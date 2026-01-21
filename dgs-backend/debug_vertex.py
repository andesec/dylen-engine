import asyncio
import os
import logging
from google import genai
from pydantic import BaseModel


async def main():
  logging.basicConfig(level=logging.INFO)
  project = os.getenv("GCP_PROJECT_ID")
  location = os.getenv("GCP_LOCATION")

  print(f"Project: {project}, Location: {location}")
  if not project or not location:
    print("Missing env vars")
    return

  client = genai.Client(vertexai=True, project=project, location=location)

  prompt = "Test prompt"
  schema = {"type": "OBJECT", "properties": {"foo": {"type": "STRING"}}}

  try:
    response = await client.aio.models.generate_content(model="gemini-2.0-flash-001", contents=prompt, config={"response_mime_type": "application/json", "response_schema": schema})
    print(response.text)
  except Exception as e:
    print(f"Error: {e}")
    import traceback

    traceback.print_exc()


if __name__ == "__main__":
  asyncio.run(main())
