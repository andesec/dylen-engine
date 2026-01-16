
import sys
import os

# Add project root to sys.path
sys.path.append(os.getcwd())

from app.ai.pipeline.contracts import GenerationRequest
from app.ai.agents.prompts import render_planner_prompt

def test_widget_rendering():
    # 1. Create a request with specific widgets
    requested_widgets = ["asciiDiagram", "codeeditor"]
    req = GenerationRequest(
        topic="Test Topic",
        depth="highlights",
        section_count=2,
        blueprint="knowledgeunderstanding",
        widgets=requested_widgets
    )

    # 2. Render the planner prompt
    prompt = render_planner_prompt(req)

    # 3. Check if the specific widgets are in the prompt
    # The prompt should contain "asciiDiagram, codeeditor" (or similar list)
    # It should NOT contain other widgets like "mcqs" or "fill_blank" if they weren't requested
    # unless the logic defaults to ALL widgets.
    
    print(f"Checking for requested widgets: {requested_widgets}")
    
    missing = []
    for w in requested_widgets:
        if w not in prompt:
            missing.append(w)
    
    if missing:
        print(f"❌ FAIL: Requested widgets missing from prompt: {missing}")
    else:
        print("✅ SUCCESS: Requested widgets found in prompt.")

    # 4. Check for leakage (optional, but good to know if it's dumping EVERYTHING)
    # We know 'mcqs' is a default widget. If it appears, it means we are ignored.
    if "mcqs" in prompt and "mcqs" not in requested_widgets:
         print(f"❌ FAIL: Unrequested widget 'mcqs' found in prompt (Prompt is ignoring preferences).")
    else:
         print("✅ SUCCESS: Unrequested widget 'mcqs' NOT found in prompt.")

if __name__ == "__main__":
    try:
        test_widget_rendering()
    except Exception as e:
        print(f"❌ ERROR: {e}")
