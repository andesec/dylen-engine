# Dylen Widget Usage Guide (Shorthand JSON Format)

This guide defines the shorthand JSON schema used by the Dynamic Learning Engine (Dylen).

Goal: keep lesson JSON compact, predictable for LLMs, and easy to render on the client.

---

## Top-Level Structure

```js
{
  "title": "Lesson Title",
  "blocks": [ /* ordered lesson content */ ]
}
```

- `title` (string, required): lesson title.
- `title` (string, required): lesson title.
- `blocks` (array, required): ordered lesson blocks. Only `section` is a valid block type.

Note:
- The Table of Contents is inferred from `section` and `subsections` titles.

Recommendations:
- Keep `title` concise (40 characters or fewer) so it fits the header without truncation.
- Keep `blocks` order logical: orientation, content, practice, assessment.

---

## Block Types

### `section` (Primary Content Card)

```json
{
  "section": "Section title",
  "markdown": ["Section intro markdown.", "left"],
  "illustration": [42, "Optional runtime caption"],
  "subsections": [
    {
      "section": "Subsection title",
      "items": [
        widgets
      ]
    }
  ]
}
```

Constraints:
- `section` must be a non-empty string.
- `markdown` is required at section level.
- `subsections` must be an array of subsection blocks.
- Every subsection block includes `section` and `items`.
- `illustration` is an image to depict the concept being discussed.

Recommendation:
- Prefer multiple shorter sections and subsections over one long section.

---

## Item Widgets (inside `items`)

Each item is either:
- an object with exactly one shorthand key, or
- a full-form widget object with `type` (advanced escape hatch).

Unless the object is a block (`section`) or uses `type`, it must use exactly one key.

Note:
- Dividers are auto-inserted between widgets when a section/subsection has multiple items.

### `markdown` (MarkdownText)

```json
{ "markdown": ["A short explanation, definition, or narrative context."] }
{ "markdown": ["**Warning:** Common pitfall / misconception."] }
{ "markdown": ["**Success:** Checkpoint: how to know you understood it."] }
{ "markdown": ["- Item 1\n- Item 2\n- Item 3"] }
{ "markdown": ["1. Step 1\n2. Step 2\n3. Step 3"] }
{ "markdown": ["Centered note.", "center"] }
{ "markdown": ["Left aligned by default.", "left"] }
```

Rules:
- Position 0 is markdown text (`md`).
- Position 1 is optional alignment: `"left"` or `"center"`.

---

### `illustration` (Visual Widget)

`illustration` uses compact shorthand: `[id, caption]`.

```json
"illustration": [42, "Visual summary caption"]
```

Rules:
- Index `0` is `id` (integer or `null`).
- Index `1` is caption string.
- Frontend media URL is built as `/media/lessons/{lesson_id}/{illustration[0]}.webp`.
- If `illustration[0]` is null/missing/empty/not an integer, frontend should skip rendering illustration.

---

### `mcqs` (Assessment Widget)

Note: `mcqs` is the canonical widget for assessments. It must be placed inside `items`.

```json
{
  "section": "Quiz",
  "items": [
    {
      "mcqs": [
        "Quiz Title",
        [
          ["Question?", ["Option A", "Option B", "Option C"], 1, "Explanation"]
        ]
      ]
    }
  ]
}
```

Constraints:
- `mcqs` array index contract:
  - `0`: quiz title (string)
  - `1`: questions array
- Each question is `[q, c, a, e]`:
  - `q` question text string
  - `c` choices array (3-4 choices recommended)
  - `a` integer (0-based correct choice index)
  - `e` explanation string

Recommendation:
- Place a quiz as the final block. Include at least 3 questions per section you taught.

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

### `swipecards` (Binary Swipe Drill)

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
{ "freeText": ["What do you mean by Clarity?.", "In my view,", "en", "clarity,structure,example,reason,summary", 123] }
```

Schema (array positions):
1. `prompt` (string): title shown above the editor.
2. `seedLocked` (string, optional): non-removable prefix.
3. `lang` (string, optional): language key. Default: `en`.
4. `wordlistCsv` (string, optional): comma-separated terms as one string.
5. `id` (integer, optional): Database ID of the subjective input widget.

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
{ "inputLine": ["Prompt text", "en", "term1,term2,term3", 123] }
```

Schema (array positions):
1. `prompt` (string): label/prompt for the input.
2. `lang` (string, optional): language code. Default: `en`.
3. `wordlistCsv` (string, optional): comma-separated terms for checking.
4. `id` (integer, optional): Database ID of the subjective input widget.

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

### `interactiveTerminal` (Guided Command Practice)

```json
{
  "interactiveTerminal": {
    "lead": "Try these commands:",
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
- `lead` (string): Title shown above the terminal.
- `rules` (array): List of `[regexString, level, outputString]` tuples.
  - `regexString`: matching pattern for user input.
  - `level`: `ok` (standard output) or `err` (error styling).
  - `outputString`: response to print.
- `guided` (array): List of `[taskHtml, solutionString]` tuples.
  - Usage: Enforces a specific sequence of commands.
  - `taskHtml`: Description shown in the guide panel. Can use `<b>`, `<code>`.
  - `solutionString`: The exact command the user must type.

Where to use:
- Interactive CLI training where you want the user to type specific commands.

---

### `terminalDemo` (Scripted Command Playback)

```json
{
  "terminalDemo": {
    "lead": "Watch the Git flow:",
    "rules": [
      ["git status", 400, "On branch main\\nnothing to commit"],
      ["git log --oneline", 600, "a1b2c3 add tests"]
    ]
  }
}
```

Schema:
- `lead` (string): Title.
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
1. `code` (string): Code to display.
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

## Best Practices (Mandatory)

1. Chunk content
   - Prefer multiple short `section` blocks over one giant section.
   - Use `subsections` when nested structure is needed.

2. Teach with a reliable loop
   - Explain with `markdown` -> translate with `tr` -> practice with `fillblank` -> checkpoint with `mcqs`.

3. End with assessment
   - Final block should be a quiz (`mcqs`) that targets the most important learning outcomes.
   - Include at least 3 questions per taught section (more is fine).

---

## Do Not

- Do not invent facts, claims, definitions, or rules.
- Do not mix multiple shorthand keys in the same item object.
- Do not omit required fields or violate required ordering in widget definitions.
- Do not number sections or subsections. The system takes care of the numbers itself.

---

## Recommended Pattern (Generic)

```json
{
  "title": "Example: A Core Concept",
  "blocks": [
    {
      "section": "What it is",
      "markdown": ["Define the concept in plain language.", "left"],
      "illustration": [42, "Quick visual of the core idea"],
      "subsections": [
        {
          "section": "Examples",
          "items": [
            { "tr": ["EN: A concrete example", "DE: Bedeutung / Ubersetzung"] },
            { "fillblank": ["Fill in: ___ is used when ...", "The concept", "Definition", "It matches the definition you learned."] }
          ]
        },
        {
          "section": "Check your understanding",
          "items": [
            {
              "mcqs": [
                "Check your understanding",
                [
                  ["What is the best description?", ["A", "B", "C"], 1, "B matches the definition; A/C miss key parts."]
                ]
              ]
            }
          ]
        }
      ]
    },
    {
      "section": "Wrap-up",
      "markdown": ["Summarize key takeaways and next steps.", "left"],
      "subsections": [
        {
          "section": "Practice",
          "items": [
            { "freeText": ["Explain the concept in your own words.", "In my view,", "en", "concept,clarity,example,summary"] }
          ]
        }
      ]
    }
  ]
}
```

---

## Section/Subsection Shape (Canonical Shorthand Output)

```json
{
  "section": "Section title",
  "markdown": ["Section intro", "left"],
  "illustration": [42, "Optional caption"],
  "subsections": [
    {
      "section": "Subsection title",
      "items": [
        { "markdown": ["Subsection content", "left"] }
      ]
    }
  ]
}
```

Where:
- `section.markdown` carries markdown in shorthand output.
- `section.illustration` is optional runtime metadata in this example shape.
- `subsections` contains subsection objects with `section` and `items`.
