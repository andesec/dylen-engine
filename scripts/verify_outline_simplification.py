import json
import sys

# Allow running from project root
sys.path.append(".")

from app.api.models import LessonOutlineResponse


def test_outline_model():
  data = {"lesson_id": "test_id", "topic": "test_topic", "title": "test_title", "sections": [{"title": "Section 1", "subsections": ["Sub 1.1", "Sub 1.2"]}]}

  try:
    response = LessonOutlineResponse(**data)
    print("Model validation successful")
    print(json.dumps(response.model_dump(), indent=2))
    assert isinstance(response.sections[0].subsections[0], str)
    print("✅ SUCCESS: subsections is a list of strings.")
  except Exception as e:
    print(f"❌ FAILED: {e}")


if __name__ == "__main__":
  test_outline_model()
