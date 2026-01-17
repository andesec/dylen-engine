﻿﻿# Checker Agent Spec (FreeText + InputLine)

## Goals
- Add a checker agent that evaluates user answers for `freeText` and `inputLine`.
- Keep widget metadata minimal: a short LLM prompt only.
- Run usability checks on the client; server focuses on security validation.
- Return a compact, consistent result for the UI.

## Non-goals
- Expanding widget schema beyond a single optional `checkPrompt`.
- Server-side rubric parsing or detailed local checks.
- Changing lesson generation behavior.

## Widget Contract Updates

### freeText (array positions)
1. `prompt` (string)
2. `seedLocked` (string, optional)
3. `lang` (string, optional, default `en`)
4. `wordlistCsv` (string, optional)
5. `checkPrompt` (string, optional) — short LLM hint/rubric

Example:
```json
{ "freeText": ["Explain X.", "In my view,", "en", "term1,term2", "Check clarity and correctness."] }
```

### inputLine (array positions)
1. `prompt` (string)
2. `lang` (string, optional, default `en`)
3. `wordlistCsv` (string, optional)
4. `checkPrompt` (string, optional) — short LLM hint/rubric

Example:
```json
{ "inputLine": ["Define latency.", "en", "latency,delay", "Check if the definition is accurate."] }
```

## Client-side Validation (UX)
- Empty/whitespace-only responses.
- Word count bounds (min/max).
- Wordlist match ratio if provided.
- Optional must-use phrases or structure.
- Immediate feedback for failed checks before calling server.

## Server-side Security Validation
- Enforce length/word limits and reject oversized payloads.
- Strip or block obvious prompt-injection patterns (e.g., “ignore previous”, “system prompt”, “developer message”).
- Reject control characters or binary payloads.
- Optional: reject serialized JSON/XML blocks in user response.
- Rate-limit per user/session if available.

## Checker Request Payload (Proposed)
```json
{
  "widgetType": "freeText|inputLine",
  "prompt": "Widget prompt",
  "lang": "en",
  "wordlistCsv": "term1,term2",
  "checkPrompt": "Short rubric",
  "responseText": "User answer",
  "seedLocked": "In my view," 
}
```

Notes:
- `seedLocked` included only for `freeText` when present.
- Client should send only fields available in the widget.

## LLM Prompt (Shape)
- System: “You are a strict evaluator. Return JSON only.”
- Context: widget prompt, optional `checkPrompt`, user answer, language.
- Output schema:
```json
{
  "ok": true,
  "issues": ["..."],
  "suggestions": ["..."],
  "feedback": "Short, user-facing feedback"
}
```

## Checker Response Payload
```json
{
  "ok": true,
  "issues": [],
  "suggestions": [],
  "feedback": "Nice work, clear and accurate.",
  "meta": {
    "model": "provider/model",
    "usage": { "prompt_tokens": 0, "completion_tokens": 0 }
  }
}
```

## Flow (High-level)
- Client runs local validation.
- If client validation passes, call server checker endpoint.
- Server performs security validation.
- Server calls LLM and returns the structured response.
- Client renders feedback + suggestions.

## Open Questions
- Max response length/word limits to enforce server-side.
- Whether to allow or reject answers that contain JSON/XML blocks.
- Whether to store checker results in job history (async vs sync).
