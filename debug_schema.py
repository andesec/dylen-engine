import msgspec
from app.schema.service import SchemaService
from app.schema.widget_models import MarkdownPayload


def debug():
  print("\n--- Testing MarkdownPayload Decoding ---")
  json_md = b'{"markdown": "Hello"}'
  try:
    res = msgspec.json.decode(json_md, type=MarkdownPayload)
    print("Success MD:", res)
  except msgspec.ValidationError as e:
    print("Error MD:", e)  # Expected to fail now since it's an object

  print("\n--- Testing MarkdownPayload Object Decoding ---")
  json_md_obj = b'{"markdown": "Hello", "align": "center"}'
  try:
    res = msgspec.json.decode(json_md_obj, type=MarkdownPayload)
    print("Success MD Obj:", res)
  except msgspec.ValidationError as e:
    print("Error MD Obj:", e)

  print("\n--- Testing Full Schema Generation & Sanitization ---")
  service = SchemaService()
  try:
    schema = service.section_schema()

    # Verify Sanitization
    sanitized = service.sanitize_schema(schema, provider_name="gemini")
    print("Sanitization completed.")

    # Helper to find booleans in 'properties' or 'items'
    def find_booleans(node, path=""):
      if isinstance(node, bool):
        print(f"Found boolean at {path}: {node}")
        return
      if isinstance(node, dict):
        for k, v in node.items():
          find_booleans(v, f"{path}.{k}")
      elif isinstance(node, list):
        for i, v in enumerate(node):
          find_booleans(v, f"{path}[{i}]")

    print("Scanning for boolean values in sanitized schema...")
    find_booleans(sanitized)

  except Exception as e:
    print(f"Schema Generation failed: {e}")


if __name__ == "__main__":
  debug()
