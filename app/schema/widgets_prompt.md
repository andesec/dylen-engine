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
{ "markdown": ["**Hello**\n\n- one\n- two"] }
{ "markdown": ["## Note\nThis is centered.", "center"] }
{ "markdown": ["Left aligned by default.", "left"] }
```

Rules:
- Position 0 is the markdown string (`md`).
- Position 1 is optional alignment: `"left"` or `"center"`.

---

### `flip` (Flipcard: prompt -> reveal)

```json
{ "flip": ["Front text (prompt)", "Back text (reveal)", "Optional front hint", "Optional back hint"] }
```

Constraints:
- The first two entries (front/back) must be strings.
- Keep the front text to 120 characters or fewer and the back text to 160 characters or fewer so the card stays legible.

---

### `tr` (Translation Pair)

```json
{ "tr": ["EN: Primary text", "DE: Translation text"] }
```

Constraints:
- Must be two strings.
- Each string must start with a 2-3 letter language code followed by `:` or `-`.

---

### `fillblank` (Fill-in-the-Blank)

```json
{ "fillblank": ["Prompt with ___", "Correct answer", "Hint", "Why it's correct"] }
```

Constraints (array order is required):
1. Prompt with `___` placeholder.
2. Correct answer string (case-insensitive matching).
3. Hint string (brief, helpful and precise).
4. Explanation string (short and concrete).

---

### `table` (Tabular Data)

```json
{ "table": [["Header A", "Header B"], ["Row 1A", "Row 1B"], ["Row 2A", "Row 2B"]] }
```

Constraints:
- Value must be a non-empty array of rows.
- First row is treated as the header.
- Cells must be strings. avoid lengthy text in the cell.

---

### `compare` (Two-Column Comparison)

```json
{ "compare": [["Left", "Right"], ["A", "B"], ["C", "D"]] }
```

Constraints:
- Value must be a non-empty array.
- First row is treated as headers.

---

### `swipecards` (Tinder like Swipe Drill)

```json
{
  "swipecards": [
    "Quick Drill: XSS Basics",
    ["No", "Yes"],
    [
      ["Store JWT in localStorage", 0, "localStorage is readable by JS; XSS can steal tokens."],
      ["Use HttpOnly cookies for sessions", 1, "HttpOnly cookies block JS access and reduce XSS impact."]
    ]
  ]
}
```

Constraints:
- Array index contract:
  - `0`: title/instruction text (string)
  - `1`: bucket labels `[leftLabel, rightLabel]`
  - `2`: cards array
- Each card is `[text, correctBucketIndex, feedback]`.
- Feedback is mandatory and shown after every swipe.
- Keep card text to 120 characters or fewer so the card stays legible.
- Keep feedback to 150 characters or fewer so it reads cleanly in the overlay.

Recommendation:
- Use when contrasting concepts, categorization, pros/cons, or before/after.

---

### `freeText` (Free Text Editor - Multiline)

```json
{ "freeText": ["What do you mean by Clarity?.", "In my view,", "en", "clarity,structure,example,reason,summary"] }
```

Schema (array positions):
1. `prompt` (string): title shown above the editor.
2. `seedLocked` (string, optional): non-removable prefix.
3. `lang` (string, optional): language key. Default: `en`.
4. `wordlistCsv` (string, optional): comma-separated terms as one string.

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
{ "inputLine": ["Prompt text", "en", "term1,term2,term3"] }
```

Schema (array positions):
1. `prompt` (string): label/prompt for the input.
2. `lang` (string, optional): language code. Default: `en`.
3. `wordlistCsv` (string, optional): comma-separated terms for checking.

Notes:
- Single-line input only.
- No seed locking.
- Checks against wordlist if provided.

---

### `stepFlow` (Step-by-step Flow with Branching)

```json
{
  "stepFlow": [
    "Follow the flow:",
    [
      "Start here.",
      [["Option A", ["Do A1"]], ["Option B", ["Do B1"]]],
      "Finish."
    ]
  ]
}
```

Schema (array positions):
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
{ "asciiDiagram": ["Diagram:", "+--+\\n|A |\\n+--+\\n"] }
```

Schema (array positions):
1. `title` (string): title shown above the diagram.
2. `diagram` (string): raw ASCII text (whitespace preserved).

Where to use:
- Architecture/flow diagrams, threat models, block diagrams, “visual via text”.

---

### `checklist` (Nested Checklist)

```json
{ "checklist": ["Use this checklist:", [["Clarity", ["Short sentences", "Avoid vague words"]]]] }
```

Schema (array positions):
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
{ "codeEditor": ["console.log('hello');", "javascript", false, [1, 3]] }
```

Schema (array positions):
1. `code` (string|object): Code to display. Objects are JSON-stringified.
2. `language` (string): Language for syntax highlighting (e.g., `javascript`, `python`).
3. `readOnly` (boolean, optional): If true, the editor is read-only. Default: false (editable).
4. `highlightedLines` (array, optional): List of 1-based line numbers to highlight.

Notes:
- Use inside `items` like any other widget.
- Provide the language whenever possible; inference works for shebangs (`#!/usr/bin/env python`) or `// language: ruby`-style comments on the first line.

Where to use:
- Interactive coding exercises, code examples with highlighting.
- Preferred over codeviewer for new content.

---

### `treeview` (Lesson Structure Viewer)

```json
{ "treeview": [{ "title": "Lesson", "blocks": [] }, "Lesson Structure", "json-input", "json-editor-view"] }
```

Schema (array positions):
1. `lesson` (object|string): lesson data with `blocks`, or JSON string.
2. `title` (string, optional): header shown above the tree.
3. `textareaId` (string, optional): editor textarea id for scroll-to-path.
4. `editorId` (string, optional): editor container id for scroll-to-path.

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
