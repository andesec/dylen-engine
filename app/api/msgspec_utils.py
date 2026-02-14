"""Utility helpers for msgspec request decoding and response encoding."""

from __future__ import annotations

import msgspec
from fastapi import HTTPException, Request, status
from starlette.responses import Response


async def decode_msgspec_request[T: msgspec.Struct](request: Request, struct_type: type[T]) -> T:
  """Decode an HTTP JSON request body into a msgspec.Struct value."""
  try:
    payload_bytes = await request.body()
    return msgspec.json.decode(payload_bytes, type=struct_type)
  except msgspec.DecodeError as exc:
    raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Invalid request payload: {exc}") from exc


def encode_msgspec_response(payload: msgspec.Struct, *, status_code: int = 200) -> Response:
  """Encode a msgspec.Struct value as a JSON HTTP response."""
  encoded = msgspec.json.encode(payload)
  return Response(content=encoded, status_code=status_code, media_type="application/json")
