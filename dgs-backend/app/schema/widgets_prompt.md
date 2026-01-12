# DLE/DGS Widget Usage Guide (Prompt)

Use this guide to format lesson widgets correctly. Keep outputs concise, factual, and aligned with the input content.

## Rules

1. Output only valid JSON.
2. Every widget must go inside `items`.
3. Each `items` entry is either:
   - a string (paragraph),
   - an object with exactly one shorthand key, or
   - a full-form widget object with `type` (advanced escape hatch).
4. Never mix multiple widget keys in one object.
5. Do not invent facts, rules, or definitions.
6. Do not manually number sections or subsections.

## Item Widgets (inside `items`)

Each item is either:
- a string (shorthand paragraph), or
- an object with exactly one shorthand key, or
- a full-form widget object with `type` (advanced escape hatch).

Unless the object is a block (`section`, `mcqs`) or uses `type`, it must use exactly one key.

Note:
- Dividers are auto-inserted between widgets when a section/subsection has multiple items.

### `p` (Paragraph)

```json
{ "p": "A short explanation, definition, or narrative context." }
```

Notes:
- A plain string is equivalent to `{ "p": "..." }`.

---

### `warn` / `err` / `success` (Callouts)

```json
{ "warn": "Common pitfall / misconception." }
{ "err": "Critical mistake or anti-pattern." }
{ "success": "Checkpoint: how to know you understood it." }
```

Recommendation:
- Keep callouts short and action-oriented so they remain skimmable.

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

### `ul` / `ol` (Lists)

```json
{ "ul": ["Item 1", "Item 2", "Item 3"] }
{ "ol": ["Step 1", "Step 2", "Step 3"] }
```

Constraints:
- Value must be an array of strings.

Recommendation:
- Use `ol` when order matters; avoid embedding numbering in the strings.

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

### `freeText` (Multi-line Free Text Editor)

```json
{ "freeText": ["What do you mean by Clarity?.", "In my view,", "", "en", "clarity,structure,example,reason,summary"] }
```

Schema (array positions):
1. `prompt` (string): title shown above the editor.
2. `seedLocked` (string, optional): non-removable prefix.
3. `text` (string): initial editable content (can be empty).
4. `lang` (string, optional): language key. Default: `en`.
5. `wordlistCsv` (string, optional): comma-separated terms as one string.

Notes:
- Wordlist checking is triggered by the “Rate my answer” button and highlights matches.
- The Wordlist button becomes available after the first rating run.
- Export produces a `.txt` with `seedLocked + text`.

Where to use:
- Writing exercises, reflections, short answers, note-taking, “explain in your own words”.
- Use `wordlistCsv` for topic-specific vocabulary learners should practice.
- Confidence checking involves usage of suggested vocabulary provided in wordlistcsv.

---

### `inputLine` (Single-line Text Input)

```json
{ "inputLine": ["What is your name?", "My name is ", "", "en"] }
```

Schema (array positions):
1. `prompt` (string): title shown above the input.
2. `seedLocked` (string, optional): non-removable prefix.
3. `text` (string): initial editable content (can be empty).
4. `lang` (string, optional): language key. Default: `en`.
5. `wordlistCsv` (string, optional): comma-separated terms as one string.

Where to use:
- Simple questions, naming, single-sentence answers.

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
1. `lead` (string): title shown above the flow.
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
1. `lead` (string): title shown above the diagram.
2. `diagram` (string): raw ASCII text (whitespace preserved).

Where to use:
- Architecture/flow diagrams, threat models, block diagrams, “visual via text”.

---

### `checklist` (Nested Checklist)

```json
{ "checklist": ["Use this checklist:", [["Clarity", ["Short sentences", "Avoid vague words"]]]] }
```

Schema (array positions):
1. `lead` (string): title shown above the checklist.
2. `tree` (array): nested items and groups.

Node formats:
- Item: `"text"`
- Group: `["groupTitle", [children...]]`

Constraints:
- Max nesting depth: 3 (including root).

Where to use:
- Verification lists, grammar checks, code review reminders, configuration reviews.

---

### `console` (Terminal Simulator)

```json
{
  "console": [
    "Try these commands (interactive):",
    1,
    [["^help$", "ok", "Commands: help, list, open <name>\\n"], [".*", "err", "Unknown command."]],
    [["Read the built-in help output.", "help"]]
  ]
}
```
```json
{
  "console": [
    "Watch a Git demo:",
    0,
    [["git status", 400, "On branch main\nnothing to commit"], ["git log -1 --oneline", 600, "a1b2c3 add tests"]]
  ]
}
```

Schema (array positions):
1. `lead` (string): title shown above the console.
2. `mode` (number): `0` = scripted demo (plays back commands), `1` = interactive (user types commands that must match regex rules).
3. `rulesOrScript` (array): demo script entries `[command, delayMs, output]` **or** interactive rules `[regex, level, output]`.
4. `guided` (array, optional): `[[task, solutionCommand], ...]`. When present in interactive mode, the console enforces that sequence and accepts only the next expected command.

Where to use:
- Guided command practice (safe simulation), workflows, CLI learning, “follow along” demos. Only use real commands from the tool being taught (Linux shell, PowerShell, Git, etc.)—never invent new commands.
- The guide panel is for rich, teachable hints (can include `<pre>`, `<code>`, paragraphs, and line breaks) that walk the learner through each meaningful step.
- Demo mode is best for “watch how this command behaves”; interactive mode is for “now you try it” with validation.

---

### `codeviewer` (Code Viewer / Editor)

```json
{ "codeviewer": ["{\n  \"hello\": \"world\"\n}", "json", false, "json-input"] }
```

Schema (array positions):
1. `code` (string|object): code to display; objects are JSON-stringified.
2. `language` (string, required): language for highlighting (e.g., `json`, `python`, `C#`).
3. `editable` (boolean, optional): shows textarea when true. Default: false.
4. `textareaId` (string, optional): id assigned to textarea when editable.

Notes:
- Use inside `items` like any other widget.
- Provide the language whenever possible; inference works for shebangs (`#!/usr/bin/env python`) or `// language: ruby`-style comments on the first line.

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
   - Prefer one `section` and multiple short `subsection` blocks over one giant section.
   - Use `subsections` when nested structure is needed.

2. End with assessment
   - Final block should be a quiz that targets the most important learning outcomes.
   - Include at least 3 questions per taught section (more is fine).

---

## Do Not

- Do not invent facts, claims, definitions, or rules.
- Do not mix multiple shorthand keys in the same item object.
- Do not omit required fields or violate required ordering in widget definitions.
- Do not number sections or subsections. The system takes care of the numbers itself.

