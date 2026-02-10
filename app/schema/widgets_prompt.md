# Dylen Widget Usage Guide (Prompt)

Use this guide to format lesson widgets correctly. Keep outputs concise, factual, and aligned with the input content.

## Rules

1. Output only valid JSON.
2. Every widget must go inside `items`.
3. Each `items` entry is either:
   - an object with exactly one shorthand key, or
   - a full-form widget object with `type` (advanced escape hatch).
4. Never mix multiple widget keys in one object.
5. Do not invent facts, rules, or definitions.
6. Do not manually number sections or subsections.

## Item Widgets (inside `items`)

Each item is either:
- an object with exactly one shorthand key.
Note:
- Dividers are auto-inserted between widgets when a section/subsection has multiple items.

### `markdown` (MarkdownText)

```json
{ "markdown": {"markdown": "**Hello**\n\n- one\n- two"} }
{ "markdown": {"markdown": "## Note\nThis is centered.", "align": "center"} }
{ "markdown": {"markdown": "Left aligned by default.", "align": "left"} }
```

Rules:
- `markdown` field is the content string.
- `align` field is optional: `"left"` or `"center"`.

---

### `flipcards` (Flipcards: prompt -> reveal)

```json
{ "flipcards": {"cards": [{"front": "Front text (prompt)", "back": "Back text (reveal)", "front_example": "Optional front example (important for vocabulary lessons)", "back_example": "Optional back example (important for vocabulary lessons)"}]} }
```

Constraints:
- `cards` is an array of flipcard objects.
- Each card requires `front` and `back` strings.
- `front_example` and `back_example` are optional. They are important for vocabulary lessons, but optional otherwise.
- There is no minimum or maximum card count.
- Keep the front text to 120 characters or fewer and the back text to 160 characters or fewer so each card stays legible.

---

### `tr` (Translation Pair)

```json
{ "tr": {"source": "EN: Primary text", "target": "DE: Translation text"} }
```

Constraints:
- Must have `source` and `target` fields.
- Each string must start with a 2-3 letter language code followed by `:` or `-`.

---

### `fillblank` (Fill-in-the-Blank)

```json
{ "fillblank": {"prompt": "Prompt with ___", "answer": "Correct answer", "hint": "Hint", "explanation": "Why it's correct"} }
```

Constraints:
1. `prompt`: text with `___` placeholder.
2. `answer`: Correct answer string (case-insensitive matching).
3. `hint`: Hint string (brief, helpful and precise).
4. `explanation`: Explanation string (short and concrete).

---

### `table` (Tabular Data)

```json
{ "table": {"rows": [["Header A", "Header B"], ["Row 1A", "Row 1B"], ["Row 2A", "Row 2B"]]} }
```

Constraints:
- `rows` value must be a non-empty array of rows.
- First row is treated as the header.
- Cells must be strings. avoid lengthy text in the cell.

---

### `compare` (Two-Column Comparison)

```json
{ "compare": {"rows": [["Left", "Right"], ["A", "B"], ["C", "D"]]} }
```

Constraints:
- `rows` value must be a non-empty array.
- First row is treated as headers.

---

### `swipecards` (Tinder like Swipe Drill)

```json
{
  "swipecards": {
    "title": "Quick Drill: XSS Basics",
    "buckets": ["No", "Yes"],
    "cards": [
      { "text": "Store JWT in localStorage", "correct_bucket_index": 0, "feedback": "localStorage is readable by JS; XSS can steal tokens." },
      { "text": "Use HttpOnly cookies for sessions", "correct_bucket_index": 1, "feedback": "HttpOnly cookies block JS access and reduce XSS impact." }
    ]
  }
}
```

Constraints:
- `title` (string): instruction text.
- `buckets` (array of 2 strings): `[leftLabel, rightLabel]`.
- `cards` (list of objects):
  - `text` (string)
  - `correct_bucket_index` (0 or 1)
  - `feedback` (mandatory string shown after swipe)
- Keep card text to 120 characters or fewer so the card stays legible.
- Keep feedback to 150 characters or fewer so it reads cleanly in the overlay.

Recommendation:
- Use when contrasting concepts, categorization, pros/cons, or before/after.

---

### `freeText` (Free Text Editor - Multiline)

```json
{ "freeText": {"prompt": "What do you mean by Clarity?.", "seed_locked": "In my view,", "lang": "en", "wordlist_csv": "clarity,structure,example,reason,summary", "ai_prompt": "Score based on clarity, structure, and usage of provided words."} }
```

Schema:
1. `prompt` (string): title shown above the editor.
2. `seed_locked` (string, optional): non-removable prefix.
3. `lang` (string, optional): language key. Default: `en`.
4. `wordlist_csv` (string, optional): comma-separated terms as one string.
5. `ai_prompt` (string, optional): Prompt used to proofread/score the input.

Notes:
- Wordlist checking is triggered by the “Rate my answer” button and highlights matches.
- The Wordlist button becomes available after the first rating run.
- Export produces a `.txt` with `seedLocked + userText`.
- Always multi-line.

Where to use:
- Writing exercises, reflections, short answers, note-taking, “explain in your own words”.
- Use `wordlistCsv` for topic-specific vocabulary learners should practice.
- Confidence checking involves usage of suggested vocabulary provided in wordlistcsv.

---

### `inputLine` (Single Line Input)

```json
{ "inputLine": {"prompt": "Prompt text", "lang": "en", "wordlist_csv": "term1,term2,term3", "ai_prompt": "Check if the answer matches the term."} }
```

Schema:
1. `prompt` (string): label/prompt for the input.
2. `lang` (string, optional): language code. Default: `en`.
3. `wordlist_csv` (string, optional): comma-separated terms for checking.
4. `ai_prompt` (string, optional): Prompt used to proofread/score the input.

Notes:
- Single-line input only.
- No seed locking.
- Checks against wordlist if provided.

---

### `stepFlow` (Step-by-step Flow with Branching)

```json
{
  "stepFlow": {
    "title": "Follow the flow:",
    "flow": [
      "Start here.",
      [["Option A", ["Do A1"]], ["Option B", ["Do B1"]]],
      "Finish."
    ]
  }
}
```

Schema:
1. `title` (string): title shown above the flow.
2. `flow` (array): steps and/or branch nodes.

Branch node format:
- `[["Choice label", [steps...]], ...]`

Constraints:
- Max branching depth: 5.

Where to use:
- Step-by-step instructions, troubleshooting flows, decision trees, learning routines.

---

### `asciiDiagram` (ASCII Diagram Panel)

```json
{ "asciiDiagram": {"title": "Diagram:", "diagram": "+--+\\n|A |\\n+--+\\n"} }
```

Schema:
1. `title` (string): title shown above the diagram.
2. `diagram` (string): raw ASCII text (whitespace preserved).

Where to use:
- Architecture/flow diagrams, threat models, block diagrams, “visual via text”.

---

### `checklist` (Nested Checklist)

```json
{ "checklist": {"title": "Use this checklist:", "tree": [["Clarity", ["Short sentences", "Avoid vague words"]]]} }
```

Schema:
1. `title` (string): title shown above the checklist.
2. `tree` (array): nested items and groups.

Node formats:
- Item: `"text"`
- Group: `["groupTitle", [children...]]`

Constraints:
- Max nesting depth: 3 (including root).

Where to use:
- Verification lists, grammar checks, code review reminders, configuration reviews.

---

### `interactiveTerminal` (Guided Command Practice)

```json
{
  "interactiveTerminal": {
    "title": "Try these commands:",
    "rules": [
      ["^help$", "ok", "Commands: help, list, open <name>\\n"],
      [".*", "err", "Unknown command."]
    ],
    "guided": [
      ["Type <b>help</b> to see commands.", "help"]
    ]
  }
}
```

Schema:
- `title` (string): Title shown above the terminal.
- `rules` (array): List of `[regexString, level, outputString]` tuples.
  - `regexString`: matching pattern for user input.
  - `level`: `ok` (standard output) or `err` (error styling).
  - `outputString`: response to print.
- `guided` (array): List of `[taskHtml, solutionString]` tuples.
  - Usage: Enforces a specific sequence of commands.
  - `taskHtml`: Description shown in the guide panel. Can use `<b>`, `<code>`.
  - `solutionString`: The exact command the user must type.

Where to use:
- Interactive CLI training where you want the user to type specific commands related to linux or a tool.

---

### `terminalDemo` (Scripted Command Playback)

```json
{
  "terminalDemo": {
    "title": "Watch the Git flow:",
    "rules": [
      ["git status", 400, "On branch main\\nnothing to commit"],
      ["git log --oneline", 600, "a1b2c3 add tests"]
    ]
  }
}
```

Schema:
- `title` (string): Title.
- `rules` (array): List of `[commandString, delayMs, outputString]` tuples.
  - `commandString`: The command to simulate typing.
  - `delayMs`: Time in milliseconds to wait before showing output (simulates processing).
  - `outputString`: The command output.

Where to use:
- Demonstrating a sequence of commands passively (user watches).

---

### `codeEditor` (Modern Code Editor)

```json
{ "codeEditor": {"code": "console.log('hello');", "language": "javascript", "read_only": false, "highlighted_lines": [1, 3]} }
```

Schema:
1. `code` (string|object): Code to display. Objects are JSON-stringified.
2. `language` (string): Language for syntax highlighting (e.g., `javascript`, `python`).
3. `read_only` (boolean, optional): If true, the editor is read-only. Default: false (editable).
4. `highlighted_lines` (array, optional): List of 1-based line numbers to highlight.

Notes:
- Use inside `items` like any other widget.
- Provide the language whenever possible; inference works for shebangs (`#!/usr/bin/env python`) or `// language: ruby`-style comments on the first line.

Where to use:
- Interactive coding exercises, code examples with highlighting.
- Preferred over codeviewer for new content.

---

### `treeview` (Lesson Structure Viewer)

```json
{ "treeview": {"lesson": [{ "title": "Lesson", "blocks": [] }], "title": "Lesson Structure", "textarea_id": "json-input", "editor_id": "json-editor-view"} }
```

Schema:
1. `lesson` (object|string): lesson data with `blocks`, or JSON string.
2. `title` (string, optional): header shown above the tree.
3. `textarea_id` (string, optional): editor textarea id for scroll-to-path.
4. `editor_id` (string, optional): editor container id for scroll-to-path.

Notes:
- When `lesson` is missing or empty, the tree shows the empty state.

---

### `mcqs` (Assessment Widget)

```json
{
  "mcqs": {
    "title": "Quiz Title",
    "questions": [
      {
        "q": "Question?",
        "c": ["Option A", "Option B", "Option C"],
        "a": 1,
        "e": "Explanation"
      }
    ]
  }
}
```

Constraints:
- `questions` must be a non-empty array.
- Each question must include:
  - `q` (string, non-empty)
  - `c` (array, at least 2 choices)
  - `a` (integer, 0-based index into `c`)
  - `e` (string, non-empty explanation)

Recommendation:
- Place a quiz as the final block. Include at least 3 questions per section you taught.

---

## Best Practices (Mandatory)

1. Chunk content
   - Prefer multiple short `section` blocks over one giant section.
   - Use `subsections` when nested structure is needed.

2. End with assessment
   - Final block should be a quiz (`mcqs`) that targets the most important learning outcomes.
   - Include at least 3 questions per taught section (more is fine).

---

## Do Not

- Do not invent facts, claims, definitions, or rules.
- Do not mix multiple shorthand keys in the same item object.
- Do not omit required fields or violate required ordering in widget definitions.
- Do not number sections or subsections. The system takes care of the numbers itself.
