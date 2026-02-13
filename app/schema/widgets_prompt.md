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
7. **Crucial:** Every widget array must end with a widget `id` (string). Use `null` or a placeholder if creating new content.

## Item Widgets (inside `items`)

### `markdown` (MarkdownText)

```json
{ "markdown": ["A short explanation.", "left", "id"] }
{ "markdown": ["Centered note.", "center", "id"] }
```

Rules:
1. Markdown text (string).
2. Alignment (optional, "left" or "center").
3. **Id** (string).

---

### `illustration` (Visual Widget)

```json
{ "illustration": ["resource_id", "Visual summary caption", "id"] }
```

Rules:
1. Resource ID (string).
2. Caption (string).
3. **Id** (string).

---

### `fenster` (Interactive HTML Widget)

```json
{ "fenster": ["Interactive demo", "Explore the concept", "resource_id", "id"] }
```

Rules:
1. Title (string).
2. Description (string).
3. Resource ID (string).
4. **Id** (string).

---

### `flipcards` (Flipcards)

```json
{ "flipcards": [[["Front", "Back", "Opt. Front Hint", "Opt. Back Hint"]], "id"] }
```

Rules:
1. Array of flipcard entries.
2. **Id** (string).

---

### `tr` (Translation Pair)

```json
{ "tr": ["EN: Primary text", "DE: Translation text", "id"] }
```

Rules:
1. Source text (string).
2. Target text (string).
3. **Id** (string).

---

### `fillblank` (Fill-in-the-Blank)

```json
{ "fillblank": ["Prompt with ___", "Correct answer", "Hint", "Why it's correct", "id"] }
```

Rules:
1. Prompt with `___`.
2. Correct answer.
3. Hint.
4. Explanation.
5. **Id** (string).

---

### `table` (Tabular Data)

```json
{ "table": [["Header A", "Header B"], ["Row 1A", "Row 1B"], "id"] }
```

Rules:
1. Array of rows (first row is header).
2. **Id** (string).

---

### `compare` (Two-Column Comparison)

```json
{ "compare": [["Left", "Right"], ["A", "B"], ["C", "D"], "id"] }
```

Rules:
1. Array of rows (first row is headers).
2. **Id** (string).

---

### `swipecards` (Binary Swipe Drill)

```json
{
  "swipecards": [
    "Quick Drill Title",
    ["LeftLabel", "RightLabel"],
    [
      ["Card Text", 0, "Feedback if swiped wrong"],
      ["Card Text", 1, "Feedback if swiped wrong"]
    ],
    "id"
  ]
}
```

Rules:
1. Title.
2. Buckets `[Left, Right]`.
3. Cards `[[text, index, feedback]]`.
4. **Id** (string).

---

### `freeText` (Free Text Editor)

```json
{ "freeText": ["Prompt?", "Seed prefix", "en", "word,list,csv", "id"] }
```

Rules:
1. Prompt.
2. Seed Locked (optional).
3. Language (optional).
4. Wordlist CSV (optional).
5. **Id** (string).

---

### `inputLine` (Single Line Input)

```json
{ "inputLine": ["Prompt text", "en", "term1,term2", "id"] }
```

Rules:
1. Prompt.
2. Language (optional).
3. Wordlist CSV (optional).
4. **Id** (string).

---

### `stepFlow` (Step-by-step Flow)

```json
{
  "stepFlow": [
    "Flow Title",
    [
      "Step 1",
      [["Option A", ["Step A1"]], ["Option B", ["Step B1"]]],
      "Finish"
    ],
    "id"
  ]
}
```

Rules:
1. Title.
2. Flow array.
3. **Id** (string).

---

### `asciiDiagram` (ASCII Diagram)

```json
{ "asciiDiagram": ["Title", "+--+\\n|A |\\n+--+\\n", "id"] }
```

Rules:
1. Title.
2. Diagram string.
3. **Id** (string).

---

### `checklist` (Nested Checklist)

```json
{ "checklist": ["Title", [["Item 1", ["Sub 1", "Sub 2"]]], "id"] }
```

Rules:
1. Title.
2. Tree array.
3. **Id** (string).

---

### `interactiveTerminal` (Guided Command Practice)

```json
{
  "interactiveTerminal": [
    "Title",
    [["^regex$", "ok", "Output"]],
    [["Type help", "help"]],
    "id"
  ]
}
```

Rules:
1. Title.
2. Rules array.
3. Guided array.
4. **Id** (string).

---

### `terminalDemo` (Scripted Command Playback)

```json
{
  "terminalDemo": [
    "Title",
    [["git status", 400, "On branch main"]],
    "id"
  ]
}
```

Rules:
1. Title.
2. Rules array.
3. **Id** (string).

---

### `codeEditor` (Modern Code Editor)

```json
{ "codeEditor": ["console.log('hi');", "javascript", false, [1], "id"] }
{ "codeEditor": ["print('hi')", "python", [1], "id"] }
```

Rules:
1. Code.
2. Language.
3. ReadOnly (optional, boolean).
4. Highlighted Lines (optional, array).
5. **Id** (string).

---

### `treeview` (Lesson Structure Viewer)

```json
{ "treeview": [{ "title": "Lesson", "blocks": [] }, "Title", "id1", "id2", "id"] }
```

Rules:
1. Lesson object.
2. Title.
3. Textarea ID.
4. Editor ID.
5. **Id** (string).

---

### `mcqs` (Assessment Widget)

```json
{
  "mcqs": [
    "Quiz Title",
    [
      ["Question?", ["Opt A", "Opt B"], 0, "Explanation"]
    ],
    "id"
  ]
}
```

Rules:
1. Title.
2. Questions array `[[Q, [C], A, E]]`.
3. **Id** (string).