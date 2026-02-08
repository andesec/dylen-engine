from __future__ import annotations

from typing import Annotated, Any, Literal

import msgspec

SECTION_TITLE_MIN_CHARS = 6
SECTION_TITLE_MAX_CHARS = 40
SUBSECTION_TITLE_MIN_CHARS = 6
SUBSECTION_TITLE_MAX_CHARS = 40
SUBSECTIONS_PER_SECTION_MIN = 1
SUBSECTIONS_PER_SECTION_MAX = 5


class Widget(msgspec.Struct):
  """Base class for all widgets."""

  pass


class MarkdownPayload(msgspec.Struct):
  markdown: Annotated[str, msgspec.Meta(min_length=30, max_length=700, description="Main markdown content (30-700 chars including symbols), break into short paragraphs as needed.")]
  align: Literal["left", "center"] = "left"

  def output(self) -> list[str]:
    return [self.markdown, self.align]


class FlipPayload(msgspec.Struct):
  front: Annotated[str, msgspec.Meta(max_length=80, description="Front prompt text (max 80 chars)")]
  back: Annotated[str, msgspec.Meta(max_length=100, description="Back reveal text (max 100 chars)")]
  front_hint: str | None = None
  back_hint: str | None = None

  def output(self) -> list[str]:
    res = [self.front, self.back]
    if self.front_hint:
      res.append(self.front_hint)
    if self.back_hint:
      res.append(self.back_hint)
    return res


class TranslationPayload(msgspec.Struct):
  source: Annotated[str, msgspec.Meta(pattern=r"^[a-zA-Z]{2,3}[:\-] .+", description="Source text with lang prefix (e.g. 'EN: Text')")]
  target: Annotated[str, msgspec.Meta(pattern=r"^[a-zA-Z]{2,3}[:\-] .+", description="Target text with lang prefix (e.g. 'DE: Text')")]

  def output(self) -> list[str]:
    return [self.source, self.target]


class FillBlankPayload(msgspec.Struct):
  prompt: Annotated[str, msgspec.Meta(pattern=r"___", description="Prompt text with '___' placeholder")]
  answer: Annotated[str, msgspec.Meta(description="The expected answer string")]
  hint: Annotated[str, msgspec.Meta(description="Brief hint for the blank")]
  explanation: Annotated[str, msgspec.Meta(description="Explanation of the correct answer")]

  def output(self) -> list[str]:
    return [self.prompt, self.answer, self.hint, self.explanation]


class FreeTextPayload(msgspec.Struct):
  prompt: Annotated[str, msgspec.Meta(min_length=1, description="Editor label text (min 1 char)")]
  seed_locked: Annotated[str | None, msgspec.Meta(description="Fixed non-removable prefix text")] = None
  lang: Annotated[str | None, msgspec.Meta(description="Language code (e.g. 'en')")] = None
  wordlist_csv: Annotated[str | None, msgspec.Meta(description="Comma-separated vocabulary terms")] = None

  def output(self) -> list[str | None]:
    res = [self.prompt]
    if self.seed_locked:
      res.append(self.seed_locked)
    if self.lang:
      res.append(self.lang)
    if self.wordlist_csv:
      res.append(self.wordlist_csv)
    return res


class InputLinePayload(msgspec.Struct):
  prompt: Annotated[str, msgspec.Meta(min_length=1, description="Input field label (min 1 char)")]
  lang: Annotated[str | None, msgspec.Meta(description="Language code (e.g. 'en')")] = None
  wordlist_csv: Annotated[str | None, msgspec.Meta(description="Comma-separated terms for validation")] = None

  def output(self) -> list[str | None]:
    res = [self.prompt]
    if self.lang:
      res.append(self.lang)
    if self.wordlist_csv:
      res.append(self.wordlist_csv)
    return res


class AsciiDiagramPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=6, max_length=40, description="Title for the proper ASCII diagram (6-40 chars)")]
  diagram: Annotated[str, msgspec.Meta(min_length=1, description="Diagram text. Make all ASCII diagram lines the same length (pad with spaces) and separate lines with \n.")]

  def output(self) -> list[str]:
    return [self.title, self.diagram]


class TerminalRule(msgspec.Struct):
  regex: str
  level: str
  output: str


class GuidedTask(msgspec.Struct):
  task_markdown: str
  solution_string: str


class InteractiveTerminalPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=6, max_length=40, description="Terminal title (6-40 chars)")]
  rules: Annotated[list[TerminalRule], msgspec.Meta(min_length=1, description="Regex-based terminal rule list (min 1 rule)")]
  guided: Annotated[list[GuidedTask] | None, msgspec.Meta(description="List of optional guided tasks")] = None

  def output(self) -> dict[str, Any]:
    return msgspec.to_builtins(self)


class DemoRule(msgspec.Struct):
  command: str
  delay_ms: int
  output: str


class TerminalDemoPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=6, max_length=40, description="Demo title (6-40 chars)")]
  rules: Annotated[list[DemoRule], msgspec.Meta(min_length=1, description="Demo step list (min 1 step)")]

  def output(self) -> dict[str, Any]:
    return msgspec.to_builtins(self)


class CodeEditorPayload(msgspec.Struct):
  code: Annotated[str, msgspec.Meta(description="Code content to display")]
  language: Annotated[str, msgspec.Meta(min_length=1, description="Syntax highlighting language (e.g. 'javascript', 'python')")]
  read_only: bool = False
  highlighted_lines: Annotated[list[int] | None, msgspec.Meta(description="List of 1-based line numbers to highlight")] = None

  def output(self) -> list[Any]:
    res = [self.code, self.language]
    if self.read_only:
      res.append(self.read_only)
    if self.highlighted_lines:
      res.append(self.highlighted_lines)
    return res


class SwipeCardPayload(msgspec.Struct):
  text: Annotated[str, msgspec.Meta(max_length=70, description="Card content text (max 70 chars)")]
  correct_bucket_index: Annotated[int, msgspec.Meta(description="Correct bucket index: 0 (left) or 1 (right)")]
  feedback: Annotated[str, msgspec.Meta(max_length=90, description="Post-swipe feedback (max 90 chars)")]

  def output(self) -> list[Any]:
    return [self.text, self.correct_bucket_index, self.feedback]


class BucketLabels(msgspec.Struct):
  left: str
  right: str


class SwipeCardsPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=6, max_length=40, description="Drill instruction title (6-40 chars)")]
  buckets: Annotated[BucketLabels, msgspec.Meta(description="Left and right bucket labels")]
  cards: Annotated[list[SwipeCardPayload], msgspec.Meta(min_length=4, description="Swipe card list (min 4 cards)")]

  def output(self) -> list[Any]:
    return [self.title, [self.buckets.left, self.buckets.right], [c.output() for c in self.cards]]


class StepFlowPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=6, max_length=40, description="Flow title (6-40 chars)")]
  flow: Annotated[list[Annotated[str | list[Any], msgspec.Meta(description="Node: 'Step' (string) or [['Choice', [substeps...]], ...] branch")]], msgspec.Meta(min_length=1, description="Sequential steps or branch nodes (max depth 4)")]

  def output(self) -> list[Any]:
    return [self.title, self.flow]


class ChecklistPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=6, max_length=40, description="Checklist title (6-40 chars)")]
  tree: Annotated[list[Annotated[str | list[Any], msgspec.Meta(description="Node: 'Item' (string) or ['Group Title', [children...]]")]], msgspec.Meta(min_length=1, description="Checklist items and groups (max depth 3)")]

  def output(self) -> list[Any]:
    return [self.title, self.tree]


class TreeViewPayload(msgspec.Struct):
  lesson: Annotated[dict[str, Any] | str | None, msgspec.Meta(description="Lesson data object or JSON string")]
  title: Annotated[str, msgspec.Meta(min_length=6, max_length=40, description="Header shown above the tree (6-40 chars)")] | None = None
  textarea_id: Annotated[str | None, msgspec.Meta(description="Editor textarea ID for scrolling")] = None
  editor_id: Annotated[str | None, msgspec.Meta(description="Editor container ID for scrolling")] = None

  def output(self) -> list[Any]:
    res = [self.lesson]
    if self.title:
      res.append(self.title)
    if self.textarea_id:
      res.append(self.textarea_id)
    if self.editor_id:
      res.append(self.editor_id)
    return res


class MCQsQuestion(msgspec.Struct):
  q: Annotated[str, msgspec.Meta(min_length=20, description="Question content (min 20 chars)")]
  c: Annotated[list[str], msgspec.Meta(min_length=3, max_length=4, description="List of 3-4 answer choices")]
  a: Annotated[int, msgspec.Meta(ge=0, description="0-based index of the correct answer")]
  e: Annotated[str, msgspec.Meta(min_length=30, description="Correct answer explanation (min 30 chars)")]

  def __post_init__(self):
    if not (0 <= self.a < len(self.c)):
      raise ValueError("mcqs answer index must be within choices range")


class MCQsInner(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=6, max_length=40, description="Quiz title (6-40 chars)")]
  questions: Annotated[list[MCQsQuestion], msgspec.Meta(min_length=1, description="Question list (min 1 question)")]

  def output(self) -> dict[str, Any]:
    return msgspec.to_builtins(self)


class FensterPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=6, max_length=40, description="Widget title (6-40 chars)")]
  description: Annotated[str, msgspec.Meta(min_length=20, description="Concept explanation text (min 20 chars)")]
  ai_prompt: Annotated[str, msgspec.Meta(min_length=50, description="AI generation prompt to create an interactive widget based on the topic using HTML/JS/CSS (min 50 chars)")]

  def output(self) -> list[str]:
    return [self.title, self.description, self.ai_prompt]


class TablePayload(msgspec.Struct):
  """Tabular data widget with header row and data rows."""

  rows: Annotated[
    list[list[str]],
    msgspec.Meta(
      min_length=2,  # At least header + 1 data row
      max_length=10,  # Header + max 9 data rows
      description="List of rows, where each row is a list of 2-6 strings. First row is the header.",
    ),
  ]

  def __post_init__(self):
    if not self.rows:
      raise ValueError("Table must have at least a header row and one data row")

    # Validate column count (2-6 columns)
    header_cols = len(self.rows[0])
    if not (2 <= header_cols <= 6):
      raise ValueError(f"Table must have 2-6 columns, got {header_cols}")

    # Validate all rows have same column count
    for i, row in enumerate(self.rows):
      if len(row) != header_cols:
        raise ValueError(f"Row {i} has {len(row)} columns, expected {header_cols}")

  def output(self) -> list[list[str]]:
    return self.rows


class CompareRow(msgspec.Struct):
  left: str
  right: str


class ComparePayload(msgspec.Struct):
  """Two-column comparison widget."""

  rows: Annotated[
    list[CompareRow],
    msgspec.Meta(
      min_length=2,  # At least header + 1 comparison
      max_length=10,  # Header + max 9 comparisons
      description="Header row + 1-9 comparison rows (exactly 2 columns)",
    ),
  ]

  def output(self) -> list[list[str]]:
    return [[r.left, r.right] for r in self.rows]


class WidgetItem(msgspec.Struct):
  """Container for any widget type (Mutually Exclusive)."""

  markdown: MarkdownPayload | None = None
  flip: FlipPayload | None = None
  tr: TranslationPayload | None = None
  fillblank: FillBlankPayload | None = None
  table: TablePayload | None = None
  compare: ComparePayload | None = None
  swipecards: SwipeCardsPayload | None = None
  free_text: FreeTextPayload | None = None
  input_line: InputLinePayload | None = None
  step_flow: StepFlowPayload | None = None
  ascii_diagram: AsciiDiagramPayload | None = None
  checklist: ChecklistPayload | None = None
  interactive_terminal: InteractiveTerminalPayload | None = None
  terminal_demo: TerminalDemoPayload | None = None
  code_editor: CodeEditorPayload | None = None
  treeview: TreeViewPayload | None = None
  mcqs: MCQsInner | None = None
  fenster: FensterPayload | None = None

  def __post_init__(self):
    # Ensure exactly one field is set
    set_fields = 0
    if self.markdown is not None:
      set_fields += 1
    if self.flip is not None:
      set_fields += 1
    if self.tr is not None:
      set_fields += 1
    if self.fillblank is not None:
      set_fields += 1
    if self.table is not None:
      set_fields += 1
    if self.compare is not None:
      set_fields += 1
    if self.swipecards is not None:
      set_fields += 1
    if self.free_text is not None:
      set_fields += 1
    if self.input_line is not None:
      set_fields += 1
    if self.step_flow is not None:
      set_fields += 1
    if self.ascii_diagram is not None:
      set_fields += 1
    if self.checklist is not None:
      set_fields += 1
    if self.interactive_terminal is not None:
      set_fields += 1
    if self.terminal_demo is not None:
      set_fields += 1
    if self.code_editor is not None:
      set_fields += 1
    if self.treeview is not None:
      set_fields += 1
    if self.mcqs is not None:
      set_fields += 1
    if self.fenster is not None:
      set_fields += 1

    if set_fields != 1:
      raise ValueError("Widget item must have exactly one widget key defined.")

  def output(self) -> dict[str, Any]:
    """Return the full shorthand object/array for the active widget."""
    if self.markdown:
      return {"markdown": self.markdown.output()}
    if self.flip:
      return {"flip": self.flip.output()}
    if self.tr:
      return {"tr": self.tr.output()}
    if self.fillblank:
      return {"fillblank": self.fillblank.output()}
    if self.table:
      return {"table": self.table.output()}
    if self.compare:
      return {"compare": self.compare.output()}
    if self.swipecards:
      return {"swipecards": self.swipecards.output()}
    if self.free_text:
      return {"freeText": self.free_text.output()}
    if self.input_line:
      return {"inputLine": self.input_line.output()}
    if self.step_flow:
      return {"stepFlow": self.step_flow.output()}
    if self.ascii_diagram:
      return {"asciiDiagram": self.ascii_diagram.output()}
    if self.checklist:
      return {"checklist": self.checklist.output()}
    if self.interactive_terminal:
      return {"interactiveTerminal": self.interactive_terminal.output()}
    if self.terminal_demo:
      return {"terminalDemo": self.terminal_demo.output()}
    if self.code_editor:
      return {"codeEditor": self.code_editor.output()}
    if self.treeview:
      return {"treeview": self.treeview.output()}
    if self.mcqs:
      return {"mcqs": self.mcqs.output()}
    if self.fenster:
      return {"fenster": self.fenster.output()}

    # Fallback to empty if somehow none are set
    return {}


class Subsection(msgspec.Struct):
  """Subsection model."""

  title: Annotated[str, msgspec.Meta(min_length=SUBSECTION_TITLE_MIN_CHARS, max_length=SUBSECTION_TITLE_MAX_CHARS, description=f"Subsection title ({SUBSECTION_TITLE_MIN_CHARS}-{SUBSECTION_TITLE_MAX_CHARS} chars)")]
  items: list[WidgetItem]

  def __post_init__(self):
    if not (1 <= len(self.items) <= 5):
      raise ValueError("Subsection items must be between 1 and 5")

  def output(self) -> dict[str, Any]:
    """Return the shorthand object for the subsection."""
    return {"section": self.title, "items": [item.output() for item in self.items], "subsections": []}


class Section(msgspec.Struct):
  """Section model."""

  title: Annotated[str, msgspec.Meta(min_length=SECTION_TITLE_MIN_CHARS, max_length=SECTION_TITLE_MAX_CHARS, description=f"Section title ({SECTION_TITLE_MIN_CHARS}-{SECTION_TITLE_MAX_CHARS} chars)")]
  markdown: MarkdownPayload
  subsections: Annotated[
    list[Subsection], msgspec.Meta(min_length=SUBSECTIONS_PER_SECTION_MIN, max_length=SUBSECTIONS_PER_SECTION_MAX, description=f"At least {SUBSECTIONS_PER_SECTION_MIN} to {SUBSECTIONS_PER_SECTION_MAX} subsections divided from the section topic")
  ]

  def __post_init__(self):
    if not (SUBSECTIONS_PER_SECTION_MIN <= len(self.subsections) <= SUBSECTIONS_PER_SECTION_MAX):
      raise ValueError(f"Section subsections must be between {SUBSECTIONS_PER_SECTION_MIN} and {SUBSECTIONS_PER_SECTION_MAX}")

  def output(self) -> dict[str, Any]:
    """Return the shorthand object for the section."""
    items = []
    if self.markdown:
      items.append({"markdown": self.markdown.output()})

    return {"section": self.title, "items": items, "subsections": [sub.output() for sub in self.subsections]}


class LessonDocument(msgspec.Struct):
  """Root lesson document."""

  title: Annotated[str, msgspec.Meta(min_length=6, max_length=40, description="Lesson title (6-40 chars)")]
  blocks: list[Section]


class RepairItem(msgspec.Struct):
  """Represents a single widget repair."""

  path: str
  widget: WidgetItem


class RepairResponse(msgspec.Struct):
  """Response model for the repair agent."""

  repairs: list[RepairItem]
