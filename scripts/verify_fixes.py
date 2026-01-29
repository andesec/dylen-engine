from app.schema.lesson_models import AsciiDiagramWidget, ParagraphWidget, TableWidget, TerminalDemoWidget, TreeViewWidget, UnorderedListWidget
from pydantic import ValidationError


def test_robust_widgets():
  print("\n--- Testing Robust Widget Validators ---")

  # 1. ParagraphWidget (List to String)
  try:
    w = ParagraphWidget(p=["Line 1", "Line 2"])
    print(f"Paragraph Coercion: {'SUCCESS' if w.p == 'Line 1\nLine 2' else 'FAILURE'}")
  except ValidationError as e:
    print(f"Paragraph Coercion FAILED: {e}")
  else:
    if w.p != "Line 1\nLine 2":
      print(f"Paragraph Coercion FAILED value mismatch: repr(w.p)={repr(w.p)}")

  # 2. UnorderedListWidget (String to List)
  try:
    w = UnorderedListWidget(ul="Single Item")
    print(f"UnorderedList Coercion: {'SUCCESS' if w.ul == ['Single Item'] else 'FAILURE'}")
  except ValidationError as e:
    print(f"UnorderedList Coercion FAILED: {e}")

  # 3. AsciiDiagramWidget (Heuristic merge)
  try:
    w = AsciiDiagramWidget(asciiDiagram=["Title", "Line 1", "Line 2"])
    print(f"AsciiDiagram Flattening: {'SUCCESS' if len(w.asciiDiagram) == 2 else 'FAILURE'}")
    if len(w.asciiDiagram) == 2:
      print(f"  Result: {w.asciiDiagram}")
  except ValidationError as e:
    print(f"AsciiDiagram Flattening FAILED: {e}")

  # 4. TableWidget (String rows)
  try:
    w = TableWidget(table=["Row 1", "Row 2"])
    print(f"Table Relaxed Input: {'SUCCESS' if w.table == [['Row 1'], ['Row 2']] else 'FAILURE'}")
  except ValidationError as e:
    print(f"Table Relaxed Input FAILED: {e}")

  # 5. TerminalDemoWidget (Auto-delay injection)
  try:
    # Input: [command, output] (missing delay)
    w = TerminalDemoWidget(terminalDemo={"lead": "Demo", "rules": [["ls", "file.txt"]]})
    rules = w.terminalDemo.rules
    if len(rules) > 0 and len(rules[0]) == 3 and rules[0][1] == 100:
      print("TerminalDemo Auto-delay: SUCCESS")
    else:
      print(f"TerminalDemo Auto-delay: FAILURE (rules={rules})")
  except ValidationError as e:
    print(f"TerminalDemo Auto-delay FAILED: {e}")

  # Retest TreeView just in case
  test_treeview_fix()


def test_treeview_fix():
  print("--- Testing TreeView Validation Fix ---")
  invalid_input = ["My Tree Title", ["Root", ["Child"]]]
  try:
    widget = TreeViewWidget(treeview=invalid_input)
    if widget.treeview[0] == ["Root", ["Child"]] and widget.treeview[1] == "My Tree Title":
      print("TreeView Auto-swap: SUCCESS")
    else:
      print("TreeView Auto-swap: FAILURE")
  except ValidationError:
    print("TreeView Auto-swap: CRASHED")


if __name__ == "__main__":
  test_robust_widgets()
