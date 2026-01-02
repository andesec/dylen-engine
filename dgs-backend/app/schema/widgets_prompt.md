# DLE/DGS Widget Reference

## 1. Rules

1. Every widget goes inside `items`:
   - is either a **string**, or
   - an **object with exactly ONE key**, or
   - a full widget using `type` (rare, advanced).
2. Never mix multiple widget keys in one object.
3. Respect **array order contracts** exactly.
4. Do **not** invent facts, rules, or definitions.
5. Do **not** number sections or subsections manually.

---

## 2. Blocks

### 2.1 Section&#x20;

```json
{
  "section": "Section title",
  "items": [],
  "subsections": []
}
```

Rules:

- `section`: non-empty string.
- `items`: array of widgets (never place widgets outside it).
- `subsections` (optional): array of **sections. Just a nested form of section, inside it cannot contain more**\*\* sections.\*\*\* \*\*
- Avoid empty `items` arrays.

Use section -> subsections to divide the content in small chunks of relevant topic -> subtopics



## 3. Core Text Widgets

### Paragraph

```json
"Plain paragraph text"
```

Equivalent to:

```json
{ "p": "Plain paragraph text" }
```

Use for explanations, definitions, narration.

---

### Callouts

```json
{ "info": "Key rule or invariant." }
{ "tip": "Practical shortcut or tactic." }
{ "warn": "Common pitfall or misconception." }
{ "err": "Critical mistake or anti-pattern." }
{ "success": "How learner knows they understood." }
```

Guidelines:

- Short, skimmable, actionable.
- Do not repeat paragraph text verbatim.

---

## 4. Knowledge Reinforcement Widgets

### Flip Card

```json
{ "flip": ["Front","Back","Front hint","Back hint"] }
```

Rules:

- First two entries required.
- Front ≤ 120 chars, back ≤ 160 chars.

Use for recall, definitions, contrasts.



### Quiz Widget

```
{ "quiz": { "title": "Quiz title", "questions": [] } }
```

Each question:

```
{ "q": "Question?", "c": ["A","B"], "a": 0, "e": "Explanation" }
```

Rules:

- `questions` must be non-empty.
- `c` must have ≥ 2 choices.
- `a` is **0-based index** into `c`.
- `e` must clearly justify the answer.

Use quizzes to **validate learning**, typically at the end of a section or lesson.

---

### Translation Pair

```json
{ "tr": ["EN: text","DE: text"] }
```

Rules:

- Exactly two strings.
- Each must start with language code + `:` or `-`.
- Use only in language learning lessons

---

### Fill‑in‑the‑Blank

```json
{ "blank": ["Prompt ___","Answer","Hint","Explanation"] }
```

Array order is mandatory.

Use for grammar, syntax, precise recall.

Always make sure the hint is explanatory for the learner.

---

## 5. Structural Widgets

### Lists

```json
{ "ul": ["A","B"] }
{ "ol": ["Step 1","Step 2"] }
```

Use `ol` only when order matters.

---

### Table

```json
{ "table": [["H1","H2"],["A","B"]] }
```

Rules:

- First row = header.
- Cells must be short strings.

---

### Compare

```json
{ "compare": [["Left","Right"],["A","B"]] }
```

Use for side‑by‑side contrasts.

---

## 6. Interactive Learning Widgets

### Swipe Drill

```json
{ "swipe": [
  "Instruction",
  ["Left","Right"],
  [["Statement",1,"Feedback"]]
] }
```

Rules:

- Feedback is mandatory.
- Card text ≤ 120 chars.

Use for categorization, pros/cons, true/false.

---

### Free Text Editor

```json
{ "freeText": ["Prompt","Seed","","en","word1,word2","multi"] }
```

Fields:

1. Prompt
2. Locked prefix (optional)
3. Initial text
4. Language (default `en`)
5. Vocabulary CSV (optional)
6. Mode: `single` | `multi`

Use for writing, reflection, explanations.

Single for one sentence answers, and multi for long text answers (upto 300 words)

---

### Step Flow

```json
{ "stepFlow": ["Lead", ["Step", [["Choice", ["Next step"]]]]] }
```

Rules:

- Branch depth ≤ 5.

Use for procedures, troubleshooting, decision trees.

---

## 7. Visualization & Practice

### ASCII Diagram

```json
{ "asciiDiagram": ["Title","+--+\n|A|\n"] }
```

Whitespace preserved.

Also for showing formatting code block.

---

### Checklist

```json
{ "checklist": ["Title", [["Group", ["Item"]]]] }
```

Rules:

- Max depth = 3.

Use for verification and reviews.

---

### Console Simulator

```json
{ "console": ["Title", 0, [["cmd",400,"output"]]] }
```

Modes:

- `0` scripted demo
- `1` interactive (regex‑validated)

Never invent commands.

---

### Code Viewer

```json
{ "codeviewer": ["code","json",false,"id"] }
```

Use for readable code blocks.

---

### Tree View

```json
{ "treeview": [{"title":"Lesson","blocks":[]},"Structure"] }
```

Shows lesson structure visually.

---

## 8. Teaching Pattern (Recommended)

1. Paragraph (`p`)
2. Insight (`info`)
3. Pitfall (`warn`)
4. Example (`tr`, `table`, or `compare`)
5. Practice (`blank`, `flip`, `swipe`, `freeText`)
6. Validation (`quiz`)

