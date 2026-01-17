from app.schema.lesson_models import LessonDocument, SectionBlock, SubsectionBlock, ParagraphWidget
from app.schema.serialize_lesson import lesson_to_shorthand
import json

def test_serialization():
    # Construct a lesson with subsections, which triggered the bug
    lesson = LessonDocument(
        title="Test Lesson",
        blocks=[
            SectionBlock(
                section="Section 1",
                items=[ParagraphWidget(p="Intro")],
                subsections=[
                    SubsectionBlock(
                        subsection="Subsection 1.1",
                        items=[ParagraphWidget(p="Details")]
                    )
                ]
            )
        ]
    )

    print("Attempting validation and serialization...")
    try:
        # validate is implicit in construction, now test serialization
        shorthand = lesson_to_shorthand(lesson)
        print("Serialization SUCCESS!")
        print(json.dumps(shorthand, indent=2))
    except AttributeError as e:
        print(f"Serialization FAILED with AttributeError: {e}")
    except Exception as e:
        print(f"Serialization FAILED with unexpected error: {e}")

if __name__ == "__main__":
    test_serialization()
