import msgspec
from app.schema.widget_models import AsciiDiagramPayload, CodeEditorPayload, DemoRule, MarkdownPayload, TerminalDemoPayload, TreeViewPayload


def test_widget_payloads() -> None:
  print("\n--- Testing msgspec widget payloads ---")
  try:
    md = MarkdownPayload(markdown="This markdown string is comfortably above thirty chars.", align="left")
    print(f"MarkdownPayload: SUCCESS ({md.output()})")
  except Exception as exc:  # noqa: BLE001
    print(f"MarkdownPayload: FAILURE ({exc})")

  try:
    ascii_diagram = AsciiDiagramPayload(title="ASCII Demo", diagram="+--+\n|A |\n+--+")
    print(f"AsciiDiagramPayload: SUCCESS ({ascii_diagram.output()})")
  except Exception as exc:  # noqa: BLE001
    print(f"AsciiDiagramPayload: FAILURE ({exc})")

  try:
    terminal_demo = TerminalDemoPayload(title="Demo Title", rules=[DemoRule(command="ls", delay_ms=100, output="file.txt")])
    print(f"TerminalDemoPayload: SUCCESS ({terminal_demo.output()})")
  except Exception as exc:  # noqa: BLE001
    print(f"TerminalDemoPayload: FAILURE ({exc})")

  try:
    code_editor = CodeEditorPayload(code="print('ok')", language="python", read_only=True, highlighted_lines=[1])
    print(f"CodeEditorPayload: SUCCESS ({code_editor.output()})")
  except Exception as exc:  # noqa: BLE001
    print(f"CodeEditorPayload: FAILURE ({exc})")

  try:
    treeview = TreeViewPayload(lesson={"title": "Lesson", "blocks": []}, title="Tree", textarea_id="json-input", editor_id="json-editor")
    print(f"TreeViewPayload: SUCCESS ({treeview.output()})")
  except Exception as exc:  # noqa: BLE001
    print(f"TreeViewPayload: FAILURE ({exc})")

  try:
    widget_item = msgspec.convert({"codeEditor": {"code": "x=1", "language": "python"}}, type=dict)
    print(f"Widget object sample parse: SUCCESS ({widget_item})")
  except Exception as exc:  # noqa: BLE001
    print(f"Widget object sample parse: FAILURE ({exc})")


if __name__ == "__main__":
  test_widget_payloads()
