# Frontend Integration: Illustration Widget

This document describes how the frontend should render illustration widgets from shorthand payloads.

## Endpoints

1. Section payload (existing flow):
   - `GET /v1/lessons/{lesson_id}/sections/{order_index}`
   - Returns the section payload in shorthand format (via the existing section retrieval flow).

2. Illustration media fetch:
   - `GET /media/lessons/{lesson_id}/{image_name}`
   - `image_name` format: `{illustration[0]}.webp`
   - Example: `/media/lessons/lesson_abc/42.webp`
   - Response headers include:
     - `Content-Type: image/webp`
     - `Cache-Control: public, max-age=3600`

## Shorthand Schema (Section + Illustration)

```json
{
  "section": "Section title",
  "markdown": ["Section intro markdown.", "left"],
  "illustration": [42, "Short visual caption"],
  "subsections": [
    {
      "section": "Subsection title",
      "items": [
        { "mcqs": ["Quick check", [["Question", ["A", "B", "C"], 1, "Why B is correct."]]] }
      ]
    }
  ]
}
```

## Rendering Rules

1. `illustration` shorthand is `[id, caption]`.
2. Render illustration only when:
   - `illustration` exists
   - `illustration[0]` is a positive integer
3. Build image URL as:
   - `imageUrl = /media/lessons/{lesson_id}/{illustration[0]}.webp`
4. If `illustration[0]` is `null` or missing:
   - Do not render the illustration block.
5. If media request returns 404:
   - Hide illustration and continue rendering the rest of the payload.

## Notes

1. Illustration shorthand intentionally exposes only `id` and `caption`.
2. Prompt/keywords remain backend metadata and are not included in shorthand output.
