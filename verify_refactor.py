import os
import sys

# Add project root to sys.path
sys.path.append(os.getcwd())

from app.schema.validate_lesson import validate_lesson


def test_validation():
  print("Running Validation Tests...")

  # 1. Flip Card Validation (Max Length)
  print("\n[Test 1] Flip Card Length Validation")
  valid_flip = {"title": "Valid Flip", "blocks": [{"section": "Section 1", "markdown": ["Intro"], "subsections": [{"title": "Sub 1", "items": [{"flip": ["Short Front", "Short Back"]}]}]}]}
  ok, errors, _ = validate_lesson(valid_flip)
  if ok:
    print("  - Valid flip passed.")
  else:
    print(f"  - Valid flip FAILED: {errors}")

  invalid_flip = {
    "title": "Invalid Flip",
    "blocks": [
      {
        "section": "Section 1",
        "markdown": ["Intro"],
        "subsections": [
          {
            "title": "Sub 1",
            "items": [{"flip": ["a" * 121, "Back"]}],  # Front > 120
          }
        ],
      }
    ],
  }
  ok, errors, _ = validate_lesson(invalid_flip)
  if not ok:
    print("  - Invalid flip (too long) correctly rejected.")
  else:
    print("  - Invalid flip INCORRECTLY PASSED!")

  # 2. Translation Pattern Validation
  print("\n[Test 2] Translation Regex Validation")
  valid_tr = {"title": "Valid Tr", "blocks": [{"section": "Sec 1", "markdown": ["Intro"], "subsections": [{"title": "Sub 1", "items": [{"tr": ["EN: Hello", "DE: Hallo"]}]}]}]}
  ok, _, _ = validate_lesson(valid_tr)
  print(f"  - Valid Translation: {'PASS' if ok else 'FAIL'}")

  invalid_tr = {"title": "Invalid Tr", "blocks": [{"section": "Sec 1", "markdown": ["Intro"], "subsections": [{"title": "Sub 1", "items": [{"tr": ["No Prefix", "DE: Hallo"]}]}]}]}
  ok, _, _ = validate_lesson(invalid_tr)
  print(f"  - Invalid Translation: {'REJECTED' if not ok else 'FAILED (Passed)'}")

  # 3. FillBlank Placeholder Validation
  print("\n[Test 3] FillBlank Validation")
  invalid_fb = {"title": "Invalid FB", "blocks": [{"section": "Sec 1", "markdown": ["Intro"], "subsections": [{"title": "Sub 1", "items": [{"fillblank": ["No Placeholder", "Ans", "Hint", "Expl"]}]}]}]}
  ok, _, _ = validate_lesson(invalid_fb)
  print(f"  - Invalid FillBlank: {'REJECTED' if not ok else 'FAILED (Passed)'}")


if __name__ == "__main__":
  try:
    test_validation()
  except Exception as e:
    print(f"Verification crashed: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)
