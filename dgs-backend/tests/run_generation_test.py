
import asyncio
import json
import os
from pathlib import Path

# Add project root to sys.path
import sys
project_root = Path(__file__).parents[2] # dgs root
sys.path.insert(0, str(project_root / "dgs-backend"))

from app.ai.orchestrator import DgsOrchestrator
from app.schema.widgets_loader import load_widget_registry

async def test_generation():
    # Load widget registry
    load_widget_registry(project_root / "dgs-backend" / "app" / "schema" / "widgets_prompt.md")

    # Initialize orchestrator
    orchestrator = DgsOrchestrator(
        gatherer_provider="gemini",
        gatherer_model="gemini-2.0-flash",
        structurer_provider="gemini",
        structurer_model="gemini-2.0-flash",
        repair_provider="gemini",
        repair_model="gemini-2.0-flash",
        schema_version="1.0"
    )

    print("--- Starting Lesson Generation (Bypass Active) ---")
    
    # Run the generation
    result = await orchestrator.generate_lesson(
        topic="Introduction to Python: Lists and Loops",
        prompt="Focus on lists and loops",
        constraints={"length": "Highlights"}
    )

    print("\n--- Generation Result ---")
    print(f"Provider A: {result.provider_a} / {result.model_a}")
    print(f"Provider B: {result.provider_b} / {result.model_b}")
    
    if result.validation_errors:
        print("\nValidation Errors:")
        for err in result.validation_errors:
            print(f"- {err}")
    else:
        print("\n✓ Validation Passed!")

    # Save result to file for inspection
    output_file = project_root / "dgs-backend" / "test_result.json"
    with open(output_file, "w") as f:
        json.dump(result.lesson_json, f, indent=2)
    
    print(f"\nLesson JSON saved to: {output_file}")
    
    # Print a snippet of the JSON
    print("\nJSON Snippet (first 500 chars):")
    print(json.dumps(result.lesson_json, indent=2)[:500] + "...")

    print("\n--- Logs ---")
    for log in result.logs:
        print(log)

if __name__ == "__main__":
    asyncio.run(test_generation())
