import json

import msgspec
from app.schema.serialize_lesson import lesson_to_shorthand
from app.schema.widget_models import LessonDocument


def test_serialization() -> None:
  lesson_payload = {
    "title": "Test Lesson",
    "blocks": [
      {
        "section": "Section 1",
        "markdown": {"markdown": "Intro text that is comfortably above thirty characters."},
        "subsections": [{"section": "Subsection 1.1", "items": [{"markdown": {"markdown": "Details text that is comfortably above thirty characters."}}]}],
      }
    ],
  }

  print("Attempting validation and serialization...")
  try:
    lesson = msgspec.convert(lesson_payload, type=LessonDocument)
    shorthand = lesson_to_shorthand(lesson)
    print("Serialization SUCCESS!")
    print(json.dumps(shorthand, indent=2))
  except Exception as exc:  # noqa: BLE001
    print(f"Serialization FAILED: {exc}")


if __name__ == "__main__":
  test_serialization()
