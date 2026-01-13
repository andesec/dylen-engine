You are an expert at molding text and JSON to a specific schema

TASK: Repair only the specific widget items that failed validation.

Rules:
- Return JSON shaped as {"repairs":[{"path":"<path>","widget":{...}}]}
- Use the provided paths exactly as given.
- Each widget must use shorthand keys with array/object fields (example: {"p":"..."} or {"fillblank":[...]}).
- Output ONLY valid JSON, no explanations.

Widgets Reference (widgets_prompt.md):
WIDGETS_DOC

Widget Schemas (only referenced types):
WIDGET_SCHEMAS

Failed Items:
FAILED_ITEMS_JSON

Errors:
ERRORS
