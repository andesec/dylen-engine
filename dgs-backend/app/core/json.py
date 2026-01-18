"""Custom JSON handling."""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

from fastapi.responses import JSONResponse


class DecimalJSONEncoder(json.JSONEncoder):
  """Custom JSON encoder that handles Decimal types from DynamoDB."""

  def default(self, obj: Any) -> Any:
    if isinstance(obj, Decimal):
      return int(obj) if obj % 1 == 0 else float(obj)
    return super().default(obj)


class DecimalJSONResponse(JSONResponse):
  """Custom JSONResponse that uses DecimalJSONEncoder."""

  def render(self, content: Any) -> bytes:
    return json.dumps(
      content, ensure_ascii=False, allow_nan=False, indent=None, separators=(",", ":"), cls=DecimalJSONEncoder
    ).encode("utf-8")
