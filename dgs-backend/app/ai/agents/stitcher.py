"""Stitcher agent implementation."""

from __future__ import annotations

from app.ai.agents.base import BaseAgent
from app.ai.pipeline.contracts import FinalLesson, JobContext, StructuredSectionBatch, StructuredSection
from copy import deepcopy
from typing import Any

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
    """Convert full-form widgets in each section payload into DLE shorthand where safe.

    Per the widget guide, each `items` entry may be:
    - a string paragraph,
    - an object with exactly one shorthand key, or
    - a full-form widget object with `type` (escape hatch).

    This method converts common full-form widgets (e.g., `{type: "info", content: ...}`)
    into shorthand equivalents (e.g., `{ "info": "..." }`) when no information would
    be lost. If the full-form contains extra fields not representable in shorthand,
    it is left as-is.
    """

    def _as_str(x: Any) -> str:
      return x if isinstance(x, str) else str(x)

    def _convert_item(item: Any) -> Any:
      # Already shorthand paragraph
      if isinstance(item, str):
        return item

      if not isinstance(item, dict):
        return item

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
        return content if isinstance(content, str) else item

      # Callouts: info/tip/warn/err/success
      if wtype in {"info", "tip", "warn", "err", "success"}:
        content = item.get("content")
        # Perfect 1:1 conversion
        if isinstance(content, str) and set(item.keys()).issubset({"type", "content"}):
          return {wtype: content}

        # Title isn't supported in shorthand; fold into message when safe
        if isinstance(content, str) and set(item.keys()).issubset({"type", "title", "content"}):
          title = item.get("title")
          if isinstance(title, str) and title.strip():
            return {wtype: f"{title.strip()}: {content}"}

        return item

      # Lists
      if wtype in {"ul", "ol"}:
        vals = item.get("items") or item.get("content")
        if isinstance(vals, list) and all(isinstance(x, str) for x in vals):
          return {wtype: vals}
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
        if isinstance(matrix, list) and matrix and all(
          isinstance(r, list) and r and all(isinstance(c, str) for c in r) for r in matrix
        ):
          return {"compare": matrix}
        return item

      # freeText (widgets_prompt.md): {"freeText": [prompt, seedLocked, text, lang, wordlistCsv, mode]}
      # If `title` exists, fold it into the prompt string to preserve information.
      if wtype == "freeText":
        known = {"type", "prompt", "seedLocked", "text", "lang", "wordlistCsv", "mode"}
        known_with_title = known | {"title"}

        prompt = item.get("prompt")
        title = item.get("title")

        if isinstance(prompt, str) and set(item.keys()).issubset(known_with_title):
          prompt_text = prompt
          if isinstance(title, str) and title.strip():
            prompt_text = f"{title.strip()}: {prompt}"

          arr: list[Any] = [
            prompt_text,
            _as_str(item.get("seedLocked") or ""),
            _as_str(item.get("text") or ""),
            _as_str(item.get("lang") or "en"),
            _as_str(item.get("wordlistCsv") or ""),
            _as_str(item.get("mode") or "multi"),
          ]
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

      # console: build the shorthand array if keys are present
      if wtype == "console":
        lead = item.get("lead") or item.get("title")
        mode = item.get("mode")
        rules_or_script = item.get("rulesOrScript") or item.get("script") or item.get("rules")
        guided = item.get("guided")
        if isinstance(lead, str) and isinstance(mode, int) and isinstance(rules_or_script, list):
          arr: list[Any] = [lead, mode, rules_or_script]
          if guided is not None:
            arr.append(guided)
          return {"console": arr}
        return item

      # codeviewer: {type, code, language, editable, textareaId} -> shorthand array
      if wtype == "codeviewer":
        code = item.get("code")
        language = item.get("language")
        if isinstance(language, str):
          editable = bool(item.get("editable", False))
          textarea_id = item.get("textareaId") or item.get("textarea_id")
          arr: list[Any] = [code, language, editable]
          if textarea_id:
            arr.append(_as_str(textarea_id))
          return {"codeviewer": arr}
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

      # quiz (widgets_prompt.md):
      # {"quiz": {"title": str, "questions": [{"q": str, "c": [..], "a": int, "e": str}, ...]}}
      # Support both:
      # - full-form batch quizzes: {type:"quiz", questions:[{text/options/answer...}, ...]}
      # - single-question quizzes: {type:"quiz", question:"...", options:[...], correctAnswer:"A"|"B"|..., feedback:"..."}
      if wtype == "quiz":
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
            return {"quiz": {"title": qtitle, "questions": out_qs}}

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

        return {"quiz": {"title": qtitle, "questions": [{"q": q_text, "c": c, "a": a_idx, "e": expl}]}}

      # Unknown or non-lossless widget: keep full-form
      return item

    def _convert_block(block: Any) -> Any:
      if not isinstance(block, dict):
        return block

      out = deepcopy(block)

      if isinstance(out.get("items"), list):
        out["items"] = [_convert_item(i) for i in out["items"]]

      if isinstance(out.get("subsections"), list):
        new_subs: list[Any] = []
        for sub in out["subsections"]:
          if isinstance(sub, dict):
            sub_out = deepcopy(sub)
            # User requirement: rename `subsection` -> `section` within subsections.
            if "subsection" in sub_out and "section" not in sub_out:
              sub_out["section"] = sub_out.pop("subsection")
            if isinstance(sub_out.get("items"), list):
              sub_out["items"] = [_convert_item(i) for i in sub_out["items"]]
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
        setattr(sec, "payload", new_payload)
      except Exception:
        # Fallback: if payload is a mutable dict, update in place
        if isinstance(payload, dict) and isinstance(new_payload, dict):
          payload.clear()
          payload.update(new_payload)

    return sections
