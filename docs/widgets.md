# Dylen Widget Usage Guide (Shorthand JSON Format)

This guide defines the shorthand JSON schema used by the Dynamic Learning Engine (Dylen).

Goal: keep lesson JSON compact, predictable for LLMs, and easy to render on the client.

---

## Top-Level Structure

```json
{
  "title": "Lesson Title",
  "blocks": [ /* ordered lesson content */ ]
}
```

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
  "illustration": ["a1ASFSAlDGalkhla8.webp", "Optional runtime caption", "a1B2c3D4e5F6g7H8"],
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
- Tracking ids and resource ids are **required in stored lesson JSON** (the client-facing payload).
- In the initial LLM output, fields that are generated later by the server (e.g., `id`, `resource_id`) may be `null` placeholders.
- Do not assume fixed array lengths when a widget includes trailing identifiers; follow the index contracts below.

### `markdown` (MarkdownText)

```json
{ "markdown": ["A short explanation, definition, or narrative context.", "left", "a1B2c3D4e5F6g7H8"] }
```

Rules (array positions):

- `0`: markdown text (string)
- `1`: alignment (string) — `"left"` or `"center"` (default: `"left"`)
- `2`: `id` (string, required) — public subsection widget id used for tracking

---

### `illustration` (Visual Widget)

illustration uses compact shorthand: [resource_id, caption, id] (section-level).

```json
"illustration": ["a1B2alsgsas8.webp", "Visual summary caption", "a1B2c3D4e5F6g7H8"]
```

Rules (array positions):

- `0`: `resource_id` (string) — public illustration resource id for media retrieval
- `1`: `caption` (string)
- `2`: `id` (string) — public subsection widget id used for learner tracking

---

### `fenster` (Interactive HTML Widget)

fenster uses shorthand: [title, description, resource_id, id].

```json
{ "fenster": ["Interactive demo", "Explore the concept", "6f5d8a8a-1f1d-4a3b-9c2a-7e9a1f3b4d5c", "a1B2c3D4e5F6g7H8"] }
```

Rules (array positions):

- `0`: `title` (string)
- `1`: `description` (string)
- `2`: `resource_id` (string) — public fenster resource id for delivery
- `3`: `id` (string) — public subsection widget id used for tracking

Frontend fenster URL: `/fenster/{resource_id}`.

---

### `mcqs` (Assessment Widget)

Note: `mcqs` is the canonical widget for assessments. It must be placed inside `items`.

```json
{
	"mcqs": [
		"Quiz Title", 
		[
			["Question?", ["Option A", "Option B", "Option C"], 1, "Explanation"]
		], 
		"a1B2c3D4e5F6g7H8"
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
  - `2`: `id` (string, required) — public subsection widget id used for tracking

Recommendation:
- Place a quiz as the final block. Include at least 3 questions per section you taught.

---

### `flipcards` (Flipcard: prompt -> reveal)

```json
{
  "flipcards": [
    [
      ["Front text (prompt)", "Back text (reveal)", "Optional front example", "Optional back example"],
      ["Front 2", "Back 2"]
    ],
    "a1B2c3D4e5F6g7H8"
  ]
}
```

Constraints:

- `flipcards[0]` is the cards array.
- Each card is `[front, back, (optional) front_example, (optional) back_example]`.
- `flipcards[1]`: `id` (string, required) — public subsection widget id used for tracking.
- Keep `front` <= 80 chars and `back` <= 100 chars.

---

### `tr` (Translation Pair)

```json
{ "tr": ["EN: Primary text", "DE: Translation text", "a1B2c3D4e5F6g7H8"] }
```

Constraints:

- Must be two strings.
- Each string must start with a 2-3 letter language code followed by `:` or `-`.
- Last element: `id` (string, required) — public subsection widget id used for tracking.

---

### `fillblank` (Fill-in-the-Blank)

```json
{ "fillblank": ["Text with ___", "Correct answer", "Hint", "Why it's correct", "a1B2c3D4e5F6g7H8"] }
```

Constraints (array order is required):

1. Text/Sentence with `___` placeholder.
2. Correct answer string (case-insensitive matching).
3. Hint string (brief, helpful and precise).
4. Explanation string (short and concrete).
5. `id` (string, required) — public subsection widget id used for tracking.

---

### `table` (Tabular Data)

```json
{
	"table": [
		["Header A", "Header B"],
		["Row 1A", "Row 1B"],
		["Row 2A", "Row 2B"],
		"a1B2c3D4e5F6g7H8"
	]
}
```

Constraints:

- Value is an array of rows (each row is an array of strings).
- First row is the header.
- Last element: `id` (string, required) — public subsection widget id used for tracking.

---

### `compare` (Two-Column Comparison)

```json
{
	"compare": [
		["Left", "Right"],
		["A", "B"],
		["C", "D"],
		"a1B2c3D4e5F6g7H8"
	]
}
```

Constraints:

- Value must be a non-empty array.
- First row is treated as headers.
- Last element: `id` (string, required) — public subsection widget id used for tracking.

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
		],
		"a1B2c3D4e5F6g7H8"
	]
}
```

Constraints:

- Array index contract:
  - `0`: title/instruction text (string)
  - `1`: bucket labels `[leftLabel, rightLabel]`
  - `2`: cards array
  - `3`: `id` (string, required) — public subsection widget id used for tracking.
- Each card is `[text, correctBucketIndex, feedback]`.
- Feedback is mandatory and shown after every swipe.
- Keep card text to 120 characters or fewer so the card stays legible.
- Keep feedback to 150 characters or fewer so it reads cleanly in the overlay.

Recommendation:

- Use when contrasting concepts, categorization, pros/cons, or before/after.

---

### `freeText` (Free Text Editor - Multiline)

```json
{ "freeText": ["What do you mean by Clarity?", "In my view,", "en", "clarity,structure,example,reason,summary", "a1B2c3D4e5F6g7H8"] }
```

Schema (array positions, trailing fields except id are optional):

1. `prompt` (string)
2. `seed_locked` (string, optional)
3. `lang` (string, optional)
4. `wordlist_csv` (string, optional)
5. `id` (string, required): public subsection widget id

---

### `inputLine` (Single Line Input)

```json
{ "inputLine": ["Prompt text", "en", "term1,term2,term3", "a1B2c3D4e5F6g7H8"] }
```

Schema (array positions, trailing fields except id are optional):

1. `prompt` (string)
2. `lang` (string, optional)
3. `wordlist_csv` (string, optional)
4. `id` (string, required): public subsection widget id

---

### `stepFlow` (Step-by-step Flow with Branching)

```json
{
  "stepFlow": [
    "Follow the flow:",
    [
      "Start here.",
      [
        ["Option A", ["Do A1"]],
        ["Option B", ["Do B1"]]
      ],
      "Finish."
    ],
    "a1B2c3D4e5F6g7H8"
  ]
}
```

Schema (array positions):

1. `title` (string): title shown above the flow.
2. `flow` (array): steps and/or branch nodes.
3. `id` (string, required): public subsection widget id

Branch node format:

- `[["Choice label", [steps...]], ...]`

Constraints:
- Max branching depth: 5.

Where to use:
- Step-by-step instructions, troubleshooting flows, decision trees, learning routines.

---

### `asciiDiagram` (ASCII Diagram Panel)

```json
{ "asciiDiagram": ["Diagram:", "+--+\n|A |\n+--+\n", "a1B2c3D4e5F6g7H8"] }
```

Schema (array positions):

1. `title` (string): title shown above the diagram.
2. `diagram` (string): raw ASCII text (whitespace preserved).
3. `id` (string, required): public subsection widget id

Where to use:
- Architecture/flow diagrams, threat models, block diagrams, “visual via text”.

---

### `checklist` (Nested Checklist)

```json
{ "checklist": ["Use this checklist:", [["Clarity", ["Short sentences", "Avoid vague words"]]], "a1B2c3D4e5F6g7H8"] }
```

Schema (array positions):

1. `title` (string): title shown above the checklist.
2. `tree` (array): nested items and groups.
3. `id` (string, required): public subsection widget id

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
	"interactiveTerminal": [
		"Try these commands:",
		[
			["^help$", "ok", "Commands: help, list, open <name>\n"],
			[".*", "err", "Unknown command."]
		],
		[["Type <b>help</b> to see commands.", "help"]],
		"a1B2c3D4e5F6g7H8"
	]
}
```

Schema (array positions):

- `0`: `title` (string): Title shown above the terminal.
- `1`: `rules` (array): List of `[regexString, level, outputString]` tuples.
  - `regexString`: matching pattern for user input.
  - `level`: `ok` (standard output) or `err` (error styling).
  - `outputString`: response to print.
- `2`: `guided` (array, optional): List of `[task_markdown, solutionString]` tuples.
  - Usage: Enforces a specific sequence of commands.
  - `task_markdown`: Description shown in the guide panel. Can use `<b>`, `<code>`.
  - `solutionString`: The exact command the user must type.
- last: `id` (string, required) — public subsection widget id

Where to use:
- Interactive CLI training where you want the user to type specific commands.

---

### `terminalDemo` (Scripted Command Playback)

```json
{
	"terminalDemo": [
		"Watch the Git flow:",
		[
			["git status", 400, "On branch main\nnothing to commit"],
			["git log --oneline", 600, "a1b2c3 add tests"]
		],
		"a1B2c3D4e5F6g7H8"
	]
}
```

Schema (array positions):

- `0`: `title` (string): Title.
- `1`: `rules` (array): List of `[commandString, delayMs, outputString]` tuples.
  - `commandString`: The command to simulate typing.
  - `delayMs`: Time in milliseconds to wait before showing output (simulates processing).
  - `outputString`: The command output.
- last: `id` (string, required) — public subsection widget id

Where to use:
- Demonstrating a sequence of commands passively (user watches).

---

### `codeEditor` (Modern Code Editor)

```json
{ "codeEditor": ["console.log('hello');", "javascript", [1, 3], "a1B2c3D4e5F6g7H8"] }
{ "codeEditor": ["print('hi')", "python", true, [2], "a1B2c3D4e5F6g7H8"] }
```

Schema (array positions, trailing fields except id are optional):

1. `code` (string)
2. `language` (string)
3. `readOnly` (boolean, optional) — only present when `true`
4. `highlightedLines` (array of ints, optional)
5. `id` (string, required): public subsection widget id

---

### `treeview` (Lesson Structure Viewer)

```json
{ "treeview": [{ "title": "Lesson", "blocks": [] }, "Lesson Structure", "json-input", "json-editor-view", "a1B2c3D4e5F6g7H8"] }
```

Schema (array positions):

1. `lesson` (object|string): lesson data with `blocks`, or JSON string.
2. `title` (string, optional): header shown above the tree.
3. `textareaId` (string, optional): editor textarea id for scroll-to-path.
4. `editorId` (string, optional): editor container id for scroll-to-path.
5. `id` (string, required): public subsection widget id

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
			"illustration": ["42.webp", "Quick visual of the core idea", "a1B2c3D4e5F6g7H8"],
			"subsections": [
				{
					"section": "Examples",
					"items": [{ "tr": ["EN: A concrete example", "DE: Bedeutung / Ubersetzung"] }, { "fillblank": ["Fill in: ___ is used when ...", "The concept", "Definition", "It matches the definition you learned."] }]
				},
				{
					"section": "Check your understanding",
					"items": [
						{
							"mcqs": ["Check your understanding", [["What is the best description?", ["A", "B", "C"], 1, "B matches the definition; A/C miss key parts."]]]
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
					"items": [{ "freeText": ["Explain the concept in your own words.", "In my view,", "en", "concept,clarity,example,summary"] }]
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
	"illustration": ["42.webp", "Optional caption", "a1B2c3D4e5F6g7H8"],
	"subsections": [
		{
			"section": "Subsection title",
			"items": [{ "markdown": ["Subsection content", "left", "a1B2c3D4e5F6g7H8"] }]
		}
	]
}
```

Where:

- `section.markdown` carries markdown in shorthand output.
- `section.illustration` is runtime metadata in this example shape.
- `subsections` contains subsection objects with `section` and `items`.
