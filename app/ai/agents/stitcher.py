"""Stitcher agent implementation."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.ai.agents.base import BaseAgent
from app.ai.pipeline.contracts import FinalLesson, JobContext, StructuredSection, StructuredSectionBatch


class StitcherAgent(BaseAgent[StructuredSectionBatch, FinalLesson]):
  """Merge structured sections into the final lesson JSON."""

  name = "Stitcher"

  async def run(self, input_data: StructuredSectionBatch, ctx: JobContext) -> FinalLesson:
    """Stitch structured sections into a final lesson payload."""
    sections = StitcherAgent._output_dle_shorthand(input_data.sections)
    lesson_json = {"title": ctx.request.topic, "blocks": [section.payload for section in sections]}
    result = self._schema_service.validate_lesson_payload(lesson_json)
    messages = [f"{issue.path}: {issue.message}" for issue in result.issues]
    metadata = {"validation_errors": messages} if messages else None
    return FinalLesson(lesson_json=lesson_json, metadata=metadata)

  @staticmethod
  def _output_dle_shorthand(sections: list[StructuredSection]) -> list[StructuredSection]:
    """Convert full-form widgets in each section payload into Dylen shorthand where safe.

    Per the widget guide, each `items` entry may be:
    - an object with exactly one shorthand key, or
    - a full-form widget object with `type` (escape hatch).

    This method converts common full-form/legacy text widgets into MarkdownText
    shorthand (`{"markdown":[...]}`) when no information would be lost.
    If the full-form contains extra fields not representable in shorthand, it is left as-is.
    """

    def _as_str(x: Any) -> str:
      return x if isinstance(x, str) else str(x)

    def _coerce_text(value: Any) -> str:
      if isinstance(value, str):
        return value.strip()
      if isinstance(value, list):
        return "\n".join(_as_str(v).strip() for v in value if _as_str(v).strip()).strip()
      return _as_str(value).strip()

    def _convert_legacy_text_item(item: dict[str, Any]) -> dict[str, Any] | None:
      align = item.get("align")
      align_value = align.strip() if isinstance(align, str) else None
      if align_value not in (None, "left", "center"):
        align_value = None

      markdown_value = item.get("markdown")
      if markdown_value is not None:
        if isinstance(markdown_value, list) and markdown_value and all(isinstance(v, str) for v in markdown_value):
          return item
        coerced = _coerce_text(markdown_value)
        if not coerced:
          return None
        payload: list[str] = [coerced]
        if align_value:
          payload.append(align_value)
        return {"markdown": payload}

      title = item.get("title")
      title_value = title.strip() if isinstance(title, str) else ""

      parts: list[str] = []

      for key in ("p", "paragraph", "callouts"):
        if key in item:
          text = _coerce_text(item.get(key))
          if not text:
            continue
          if title_value:
            parts.append(f"### {title_value}\n{text}")
            title_value = ""
          else:
            parts.append(text)

      callout_labels = {"info": "Note", "warn": "Warning", "warning": "Warning", "err": "Error", "error": "Error", "success": "Success"}
      for key in ("info", "warn", "warning", "err", "error", "success"):
        if key in item:
          text = _coerce_text(item.get(key))
          if not text:
            continue
          prefix = f"{title_value}: " if title_value else ""
          if title_value:
            title_value = ""
          label = callout_labels[key]
          parts.append(f"**{label}:** {prefix}{text}")

      for key in ("ul", "ol"):
        if key in item:
          vals = item.get(key)
          if not isinstance(vals, list) or not vals:
            continue
          entries = [_as_str(v).strip() for v in vals if _as_str(v).strip()]
          if not entries:
            continue
          if key == "ul":
            parts.append("\n".join(f"- {entry}" for entry in entries))
          else:
            parts.append("\n".join(f"{idx + 1}. {entry}" for idx, entry in enumerate(entries)))

      md = "\n\n".join(part for part in parts if part.strip()).strip()
      if not md:
        return None

      payload: list[str] = [md]
      if align_value:
        payload.append(align_value)
      return {"markdown": payload}

    def _convert_item(item: Any) -> Any:
      # Convert raw strings into MarkdownText to keep output schema strict.
      if isinstance(item, str):
        content = item.strip()
        if not content:
          return None
        return {"markdown": [content]}

      if not isinstance(item, dict):
        return item

      if "type" not in item:
        legacy_keys = {"markdown", "p", "paragraph", "callouts", "info", "warn", "warning", "err", "error", "success", "ul", "ol"}
        if any(key in item for key in legacy_keys):
          converted = _convert_legacy_text_item(item)
          if converted is None:
            return None
          return converted

      # Already shorthand object (e.g., {"info": "..."}, {"table": [...]}, etc.)
      # If there is no `type` key, do nothing.
      if "type" not in item:
        return item

      # Full-form widget object uses `type` as the escape hatch.
      wtype = item.get("type")
      if not wtype:
        return item

      # Paragraph-ish full form
      if wtype in {"p", "paragraph", "text"}:
        content = item.get("content") or item.get("text")
        if isinstance(content, str) and content.strip():
          return {"markdown": [content.strip()]}
        return item

      # Callouts: info/tip/warn/err/success
      if wtype in {"info", "tip", "warn", "err", "success"}:
        content = item.get("content")
        if not isinstance(content, str) or not content.strip():
          return item
        title = item.get("title")
        title_prefix = ""
        if isinstance(title, str) and title.strip():
          title_prefix = f"{title.strip()}: "
        label = "Warning" if wtype == "warn" else "Error" if wtype == "err" else "Success" if wtype == "success" else "Note"
        return {"markdown": [f"**{label}:** {title_prefix}{content.strip()}"]}

      # Lists
      if wtype in {"ul", "ol"}:
        vals = item.get("items") or item.get("content")
        if isinstance(vals, list) and all(isinstance(x, str) for x in vals):
          lines = [f"- {x.strip()}" for x in vals] if wtype == "ul" else [f"{idx + 1}. {x.strip()}" for idx, x in enumerate(vals)]
          return {"markdown": ["\n".join(lines)]}
        return item

      # Table (widgets_prompt.md): {"table": [[headers...], [row...], ...]}
      # Convert only when we can do so without dropping fields (e.g., no `title`).
      if wtype == "table":
        allowed = {"type", "headers", "rows"}
        if not set(item.keys()).issubset(allowed):
          return item

        headers = item.get("headers")
        rows = item.get("rows")
        if isinstance(headers, list) and headers and all(isinstance(x, str) for x in headers) and isinstance(rows, list) and rows:
          table_rows: list[list[str]] = [headers]
          for r in rows:
            if not (isinstance(r, list) and r and all(isinstance(c, str) for c in r)):
              return item
            table_rows.append(r)
          return {"table": table_rows}
        return item

      # Compare (widgets_prompt.md): {"compare": [[L,R], [..], ..]} (matrix form only)
      # Convert only if already matrix-like and no extra fields (e.g., no `title`).
      if wtype == "compare":
        allowed = {"type", "matrix", "rows"}
        if not set(item.keys()).issubset(allowed):
          return item

        matrix = item.get("matrix") or item.get("rows")
        if isinstance(matrix, list) and matrix and all(isinstance(r, list) and r and all(isinstance(c, str) for c in r) for r in matrix):
          return {"compare": matrix}
        return item

      # freeText (widgets_prompt.md): {"freeText": [prompt, seedLocked, lang, wordlistCsv]}
      # If `title` exists, fold it into the prompt string to preserve information.
      if wtype == "freeText":
        known = {"type", "prompt", "seedLocked", "lang", "wordlistCsv"}
        known_with_title = known | {"title"}

        prompt = item.get("prompt")
        title = item.get("title")

        if isinstance(prompt, str) and set(item.keys()).issubset(known_with_title):
          prompt_text = prompt

          if isinstance(title, str) and title.strip():
            prompt_text = f"{title.strip()}: {prompt}"

          arr: list[Any] = [prompt_text, _as_str(item.get("seedLocked") or ""), _as_str(item.get("lang") or "en"), _as_str(item.get("wordlistCsv") or "")]
          return {"freeText": arr}

        # Some models incorrectly emit {type: freeText, content: "..."} as a generic text blob.
        content = item.get("content")
        if isinstance(content, str):
          return content

        return item

      # stepFlow: {type, title/lead, steps/flow} -> {stepFlow: [lead, flow]}
      if wtype == "stepFlow":
        known = {"type", "title", "steps", "lead", "flow"}
        lead = item.get("lead") or item.get("title")
        flow = item.get("flow") or item.get("steps")
        if isinstance(lead, str) and isinstance(flow, list) and set(item.keys()).issubset(known):
          return {"stepFlow": [lead, flow]}
        return item

      # checklist: {type, title/lead, items/tree} -> {checklist: [lead, tree]}
      if wtype == "checklist":
        known = {"type", "title", "items", "lead", "tree"}
        lead = item.get("lead") or item.get("title")
        tree = item.get("tree") or item.get("items")
        if isinstance(lead, str) and isinstance(tree, list) and set(item.keys()).issubset(known):
          return {"checklist": [lead, tree]}
        return item

      # asciiDiagram: {type, lead/title, diagram/content} -> {asciiDiagram: [lead, diagram]}
      if wtype == "asciiDiagram":
        known = {"type", "lead", "title", "diagram", "content"}
        lead = item.get("lead") or item.get("title") or "Diagram:"
        diagram = item.get("diagram") or item.get("content")
        if isinstance(lead, str) and isinstance(diagram, str) and set(item.keys()).issubset(known):
          return {"asciiDiagram": [lead, diagram]}
        return item

      # interactiveTerminal: convert full-form fields into the supported payload shape
      if wtype == "interactiveTerminal":
        lead = item.get("lead") or item.get("title")
        rules = item.get("rules")
        guided = item.get("guided")
        if isinstance(lead, str) and isinstance(rules, list):
          payload: dict[str, Any] = {"lead": lead, "rules": rules}
          if guided is not None:
            payload["guided"] = guided
          return {"interactiveTerminal": payload}
        return item

      # terminalDemo: convert full-form fields into the supported payload shape
      if wtype == "terminalDemo":
        lead = item.get("lead") or item.get("title")
        rules = item.get("rules")
        if isinstance(lead, str) and isinstance(rules, list):
          return {"terminalDemo": {"lead": lead, "rules": rules}}
        return item

      # codeEditor: {type, code, language, readOnly, highlightedLines} -> shorthand array
      if wtype == "codeEditor":
        code = item.get("code")
        language = item.get("language")
        if isinstance(language, str):
          read_only = bool(item.get("readOnly", False))
          highlighted_lines = item.get("highlightedLines")
          arr: list[Any] = [code, language, read_only]
          if highlighted_lines is not None and isinstance(highlighted_lines, list):
            arr.append(highlighted_lines)
          elif highlighted_lines is not None:
            return item
          return {"codeEditor": arr}
        return item

      # treeview: {type, lesson, title, textareaId, editorId} -> shorthand array
      if wtype == "treeview":
        lesson = item.get("lesson")
        if lesson is not None:
          arr: list[Any] = [lesson]
          if item.get("title") is not None:
            arr.append(item.get("title"))
          if item.get("textareaId") is not None:
            arr.append(item.get("textareaId"))
          if item.get("editorId") is not None:
            arr.append(item.get("editorId"))
          return {"treeview": arr}
        return item

      # mcqs (widgets_prompt.md):
      # {"mcqs": {"title": str, "questions": [{"q": str, "c": [..], "a": int, "e": str}, ...]}}
      # Support both:
      # - full-form batch quizzes: {type:"quiz"|"mcqs", questions:[{text/options/answer...}, ...]}
      # - single-question quizzes: {type:"quiz"|"mcqs", question:"...", options:[...], correctAnswer:"A"|"B"|..., feedback:"..."}
      if wtype in {"quiz", "mcqs"}:
        qtitle = item.get("title") if isinstance(item.get("title"), str) else "Quiz"

        # Case 1: full-form batch quiz
        qs = item.get("questions")
        if isinstance(qs, list):
          out_qs: list[dict[str, Any]] = []
          for q in qs:
            if not isinstance(q, dict):
              continue

            q_text = q.get("q") or q.get("text") or q.get("question")
            choices = q.get("c") or q.get("options") or q.get("choices")

            if not isinstance(q_text, str) or not isinstance(choices, list) or len(choices) < 2:
              continue

            c = [_as_str(x) for x in choices]

            # Answer may be an index or a choice string
            if isinstance(q.get("a"), int):
              a_idx = int(q["a"])
            elif isinstance(q.get("answer"), int):
              a_idx = int(q["answer"])
            elif isinstance(q.get("answer"), str):
              try:
                a_idx = c.index(q["answer"])
              except ValueError:
                a_idx = 0
            else:
              a_idx = 0

            if a_idx < 0 or a_idx >= len(c):
              a_idx = 0

            expl = q.get("e") or q.get("explanation")
            if not isinstance(expl, str) or not expl.strip():
              expl = f"Correct: {c[a_idx]}."

            out_qs.append({"q": q_text, "c": c, "a": a_idx, "e": expl})

          if out_qs:
            return {"mcqs": {"title": qtitle, "questions": out_qs}}

          return item

        # Case 2: single-question quiz
        q_text = item.get("question") or item.get("text")
        choices = item.get("options") or item.get("choices")
        if not isinstance(q_text, str) or not isinstance(choices, list) or len(choices) < 2:
          return item

        c = [_as_str(x) for x in choices]

        # correctAnswer may be a letter (A/B/C...), 0/1-based index, or a choice string
        ca = item.get("correctAnswer") or item.get("answer")
        a_idx = 0
        if isinstance(ca, int):
          a_idx = int(ca)
        elif isinstance(ca, str):
          s = ca.strip()
          if len(s) == 1 and s.upper() in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
            a_idx = ord(s.upper()) - ord("A")
          else:
            # try parse int (1-based then 0-based)
            try:
              n = int(s)
              a_idx = n - 1 if n > 0 else 0
            except Exception:
              try:
                a_idx = c.index(ca)
              except ValueError:
                a_idx = 0

        if a_idx < 0 or a_idx >= len(c):
          a_idx = 0

        expl = item.get("feedback") or item.get("explanation")
        if not isinstance(expl, str) or not expl.strip():
          expl = f"Correct: {c[a_idx]}."

        return {"mcqs": {"title": qtitle, "questions": [{"q": q_text, "c": c, "a": a_idx, "e": expl}]}}

      # Unknown or non-lossless widget: keep full-form
      return item

    def _convert_block(block: Any) -> Any:
      if not isinstance(block, dict):
        return block

      out = deepcopy(block)

      if isinstance(out.get("items"), list):
        items: list[Any] = []
        for entry in out["items"]:
          converted = _convert_item(entry)
          if converted is None:
            continue
          items.append(converted)
        out["items"] = items

      if isinstance(out.get("subsections"), list):
        new_subs: list[Any] = []
        for sub in out["subsections"]:
          if isinstance(sub, dict):
            sub_out = deepcopy(sub)
            # User requirement: rename `subsection` -> `section` within subsections.
            if "subsection" in sub_out and "section" not in sub_out:
              sub_out["section"] = sub_out.pop("subsection")
            if isinstance(sub_out.get("items"), list):
              items: list[Any] = []
              for entry in sub_out["items"]:
                converted = _convert_item(entry)
                if converted is None:
                  continue
                items.append(converted)
              sub_out["items"] = items
            new_subs.append(sub_out)
          else:
            new_subs.append(sub)
        out["subsections"] = new_subs

      return out

    for sec in sections:
      # Mutate in place (safest: preserves any extra fields on the StructuredSection model)
      payload = getattr(sec, "payload", None)
      if payload is None:
        continue

      new_payload = _convert_block(payload)

      try:
        sec.payload = new_payload
      except Exception:
        # Fallback: if payload is a mutable dict, update in place
        if isinstance(payload, dict) and isinstance(new_payload, dict):
          payload.clear()
          payload.update(new_payload)

    return sections
