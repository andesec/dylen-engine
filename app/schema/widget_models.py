from __future__ import annotations

from typing import Annotated, Any, Literal

import msgspec


class Widget(msgspec.Struct):
  """Base class for all widgets."""

  pass


class MarkdownPayload(msgspec.Struct):
  markdown: Annotated[str, msgspec.Meta(min_length=30, max_length=600, description="Markdown text content")]
  align: Literal["left", "center"] | None = None

  def output(self) -> list[str]:
    return [self.markdown, self.align] if self.align else [self.markdown]


class FlipPayload(msgspec.Struct):
  front: Annotated[str, msgspec.Meta(max_length=80, description="Front text (prompt)")]
  back: Annotated[str, msgspec.Meta(max_length=120, description="Back text (reveal)")]
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
  source: Annotated[str, msgspec.Meta(pattern=r"^[a-zA-Z]{2,3}[:\-] .+", description="Source text with lang prefix (e.g. 'EN: Hello')")]
  target: Annotated[str, msgspec.Meta(pattern=r"^[a-zA-Z]{2,3}[:\-] .+", description="Target text with lang prefix (e.g. 'DE: Hallo')")]

  def output(self) -> list[str]:
    return [self.source, self.target]


class FillBlankPayload(msgspec.Struct):
  prompt: Annotated[str, msgspec.Meta(pattern=r"___", description="Prompt with '___' placeholder")]
  answer: Annotated[str, msgspec.Meta(description="Correct answer")]
  hint: Annotated[str, msgspec.Meta(description="Short but clear hint")]
  explanation: Annotated[str, msgspec.Meta(description="Explanation for the answer")]

  def output(self) -> list[str]:
    return [self.prompt, self.answer, self.hint, self.explanation]


class FreeTextPayload(msgspec.Struct):
  prompt: Annotated[str, msgspec.Meta(min_length=1, description="Title shown above the editor")]
  seed_locked: Annotated[str | None, msgspec.Meta(description="Non-removable prefix text")] = None
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
  prompt: Annotated[str, msgspec.Meta(min_length=1, description="Label/prompt for the input")]
  lang: Annotated[str | None, msgspec.Meta(description="Language code (e.g. 'en')")] = None
  wordlist_csv: Annotated[str | None, msgspec.Meta(description="Comma-separated terms for checking")] = None

  def output(self) -> list[str | None]:
    res = [self.prompt]
    if self.lang:
      res.append(self.lang)
    if self.wordlist_csv:
      res.append(self.wordlist_csv)
    return res


class AsciiDiagramPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=1, description="Title shown above the diagram")]
  diagram: Annotated[str, msgspec.Meta(min_length=1, description="Raw ASCII text (whitespace preserved)")]

  def output(self) -> list[str]:
    return [self.title, self.diagram]


class InteractiveTerminalPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=1, description="Title shown above the terminal")]
  rules: Annotated[list[tuple[str, str, str]], msgspec.Meta(min_length=1, description="List of (regexString, level, outputString) tuples")]
  guided: Annotated[list[tuple[str, str]] | None, msgspec.Meta(description="List of (taskMarkdown, solutionString) tuples for guided mode")] = None


class TerminalDemoPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=1, description="Title shown above the demo")]
  rules: Annotated[list[tuple[str, int, str]], msgspec.Meta(min_length=1, description="List of (commandString, delayMs, outputString) tuples")]


class CodeEditorPayload(msgspec.Struct):
  code: Annotated[str, msgspec.Meta(description="Code to display (string)")]
  language: Annotated[str, msgspec.Meta(min_length=1, description="Language for syntax highlighting (e.g. 'javascript', 'python')")]
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
  text: Annotated[str, msgspec.Meta(max_length=120, description="Card text")]
  correct_bucket_index: Annotated[int, msgspec.Meta(description="Correct bucket index (0 or 1)")]
  feedback: Annotated[str, msgspec.Meta(max_length=150, description="Feedback shown after swipe")]

  def output(self) -> list[Any]:
    return [self.text, self.correct_bucket_index, self.feedback]


class SwipeCardsPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=1, description="Title/instruction text for the drill")]
  buckets: Annotated[tuple[str, str], msgspec.Meta(description="Bucket labels (leftLabel, rightLabel)")]
  cards: Annotated[list[SwipeCardPayload], msgspec.Meta(min_length=1, description="List of swipe cards")]

  def output(self) -> list[Any]:
    return [self.title, self.buckets, [c.output() for c in self.cards]]


class StepFlowPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=1, description="Title shown above the flow")]
  flow: Annotated[list[Any], msgspec.Meta(min_length=1, description="Steps and/or branch nodes (max depth: 5)")]

  def output(self) -> list[Any]:
    return [self.title, self.flow]


class ChecklistPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=1, description="Title shown above the checklist")]
  tree: Annotated[list[Any], msgspec.Meta(min_length=1, description="Nested items and groups (max depth: 3)")]

  def output(self) -> list[Any]:
    return [self.title, self.tree]


class TreeViewPayload(msgspec.Struct):
  lesson: Annotated[dict[str, Any] | str | None, msgspec.Meta(description="Lesson data with blocks, or JSON string")]
  title: Annotated[str | None, msgspec.Meta(description="Header shown above the tree")] = None
  textarea_id: Annotated[str | None, msgspec.Meta(description="Editor textarea ID for scroll-to-path")] = None
  editor_id: Annotated[str | None, msgspec.Meta(description="Editor container ID for scroll-to-path")] = None

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
  q: Annotated[str, msgspec.Meta(min_length=1, description="Question text")]
  c: Annotated[list[str], msgspec.Meta(min_length=3, max_length=4, description="Answer choices (3-4)")]
  a: Annotated[int, msgspec.Meta(ge=0, description="Correct answer index (0-based)")]
  e: Annotated[str, msgspec.Meta(min_length=1, description="Explanation for the correct answer")]

  def __post_init__(self):
    if not (0 <= self.a < len(self.c)):
      raise ValueError("mcqs answer index must be within choices range")


class MCQsInner(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=1, description="Quiz title")]
  questions: Annotated[list[MCQsQuestion], msgspec.Meta(min_length=1, description="List of questions (at least 1)")]


class FensterPayload(msgspec.Struct):
  title: Annotated[str, msgspec.Meta(min_length=1, description="Widget title")]
  description: Annotated[str, msgspec.Meta(min_length=1, description="Description text explaining the concept")]
  ai_prompt: Annotated[str, msgspec.Meta(min_length=1, description="Prompt for AI to generate HTML/JS/CSS implementation")]

  def output(self) -> list[str]:
    return [self.title, self.description, self.ai_prompt]


class TablePayload(msgspec.Struct):
  """Tabular data widget with header row and data rows."""

  rows: Annotated[
    list[list[str]],
    msgspec.Meta(
      min_length=2,  # At least header + 1 data row
      max_length=16,  # Header + max 15 data rows
      description="Table rows (first row is header, 2-6 columns, 2-15 data rows)",
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
    return [self.rows]


class ComparePayload(msgspec.Struct):
  """Two-column comparison widget."""

  rows: Annotated[
    list[tuple[str, str]],
    msgspec.Meta(
      min_length=2,  # At least header + 1 comparison
      max_length=16,  # Header + max 15 comparisons
      description="Comparison rows (first row is headers, exactly 2 columns)",
    ),
  ]

  def output(self) -> list[list[tuple[str, str]]]:
    return [self.rows]


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


class Subsection(msgspec.Struct):
  """Subsection model."""

  title: Annotated[str, msgspec.Meta(min_length=5, max_length=60, description="Subsection title")]
  items: list[WidgetItem]

  def __post_init__(self):
    if not (1 <= len(self.items) <= 5):
      raise ValueError("Subsection items must be between 1 and 5")


class Section(msgspec.Struct):
  """Section model."""

  title: Annotated[str, msgspec.Meta(min_length=5, max_length=60, description="Section title")]
  markdown: MarkdownPayload
  subsections: list[Subsection]

  def __post_init__(self):
    if not (1 <= len(self.subsections) <= 8):
      raise ValueError("Section subsections must be between 1 and 8")


class LessonDocument(msgspec.Struct):
  """Root lesson document."""

  title: Annotated[str, msgspec.Meta(max_length=60, description="Lesson title")]
  blocks: list[Section]
